# app/llm.py
"""
LLM-facing utilities:
- Build compact batch context for the model
- Call Ollama in strict-JSON mode (retry on bad output)
- Clean/normalize model headlines (keep apostrophes & hyphens)
- Drop unsafe/NSFW outputs
- Fall back to extractive headlines if the model fails
"""

import re
import json
import requests
import textwrap
import unicodedata
from typing import List, Dict
from collections import Counter

from config import Settings
from cleaning import strip_admin_markup
from scoring import simple_fallback_headlines  # robust, never-empty fallback

# Words we never want in final headlines (keep small and targeted)
OFF_LIMIT = {
    # sexual / explicit / profane – extend only if needed
    "masturbate", "masturbation", "porn", "pornography", "xxx",
    "sex", "sexual", "fetish", "nsfw",
    # add any absolutely off-limits terms here
}

# Boilerplate / namespace-y tokens to drop from generations
BAN_WORDS = {
    "whatlinkshere", "special", "wikiproject", "talk",
    "articles", "class", "stub", "category", "categories", "wp",
}

# ---------------------------------------------------------------------
# Context builder (for the whole window)
# ---------------------------------------------------------------------

def batch_context(entries: List[Dict], max_chars: int = 600) -> str:
    """Summarize the window with common terms + a few short examples."""
    words, examples = [], []
    for e in entries[:8]:
        txt = strip_admin_markup(f'{e.get("title","")}: {e.get("comment","")}')
        examples.append((txt[:140] + "...") if len(txt) > 140 else txt)
        words += re.findall(r"\b[a-zA-Z]{5,}\b", txt)
    common = ", ".join([w for w, _ in Counter(w.lower() for w in words).most_common(15)])
    blob = f"Common terms: {common}\nExamples:\n- " + "\n- ".join(examples)
    return blob[:max_chars]

# ---------------------------------------------------------------------
# Headline post-processing
# ---------------------------------------------------------------------

def _strip_bad_punct_keep_apostrophe(s: str) -> str:
    """Remove links/angle/quote clutter; keep letters/spaces/'/- and collapse spaces."""
    s = re.sub(r"\[\[|\]\]|\{|\}|\(|\)|<|>|https?://\S+", " ", s)
    s = s.replace("“", " ").replace("”", " ").replace("«", " ").replace("»", " ").replace('"', " ")
    return re.sub(r"\s+", " ", s).strip()

def _contains_off_limit(s: str) -> bool:
    """True if any off-limit token appears as a word."""
    return any(tok in OFF_LIMIT for tok in re.findall(r"\b[a-z']+\b", s.lower()))

def sanitize_headline(h: str) -> str:
    """Return '' if unsafe; else the headline unchanged."""
    return "" if _contains_off_limit(h) else h

def clean_headline(h: str, max_words: int) -> str:
    """
    NFC normalize, drop banned tokens, cap to `max_words`,
    allow either short sentence or noun phrase (min 2 words),
    keep apostrophes & hyphens.
    """
    # tolerate dict-like JSON
    try:
        if isinstance(h, str) and h.lstrip().startswith("{"):
            obj = json.loads(h)
            if isinstance(obj, dict):
                h = " ".join(str(v) for v in obj.values() if isinstance(v, (str, int, float)))
    except Exception:
        pass

    h = unicodedata.normalize("NFC", str(h))
    h = _strip_bad_punct_keep_apostrophe(h)

    words = [w for w in h.split() if w.lower() not in BAN_WORDS][:max_words]
    if len(words) < 2:  # allow noun phrases: minimum 2 words
        return ""

    # gentle lead-cap
    h = " ".join(words)
    if h:
        h = h[0].upper() + h[1:]
    return h.strip(" -:")

# ---------------------------------------------------------------------
# JSON parsing + Ollama call
# ---------------------------------------------------------------------

def _parse_json_array(text: str) -> List[str]:
    """Return list of strings if `text` is/contains a JSON array; else []."""
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data if isinstance(x, (str, int, float))]
        if isinstance(data, dict):  # sometimes the model replies with an object
            return [str(v) for v in data.values() if isinstance(v, (str, int, float))]
    except Exception:
        pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [str(x) for x in arr if isinstance(x, (str, int, float))]
        except Exception:
            return []
    return []

def _call_ollama(prompt: str, s: Settings, temperature: float) -> str:
    """One Ollama call in strict JSON mode; return raw response string."""
    r = requests.post(
        f"{s.ollama_host}/api/generate",
        json={
            "model": s.ollama_model,
            "prompt": prompt,
            "options": {
                "temperature": max(0.5, temperature - 0.1),  # slightly cooler for stability
                "seed": s.seed,
                "num_ctx": s.num_ctx,
                "num_gpu": s.num_gpu,
                "top_p": 0.9,
                "top_k": 40,
            },
            "format": "json",      # <- ask for JSON tokenization
            "stream": False,
        },
        timeout=getattr(s, "request_timeout_s", 60),
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()

# ---------------------------------------------------------------------
# Public: generate N headlines for a window
# ---------------------------------------------------------------------

def generate_batch_headlines(entries: List[Dict], mood: str, s: Settings, n: int) -> List[str]:
    """
    Try twice to get valid JSON headlines from the model; if it still
    fails, fall back to extractive headlines so output is never empty.
    """
    rules = (
        "Write newsroom-style headlines. Each headline must be either: "
        "(a) a concise, grammatical sentence, OR (b) a clean noun phrase. "
        f"Hard cap: ≤{s.max_words} words. Professional tone. No slang, no emojis. "
        "Letters and spaces only (keep apostrophes and hyphens). "
        "Avoid bare namespaces (Category, Talk, WikiProject) and boilerplate. "
        "Do NOT use explicit/sexual/profane words. "
        "Do NOT mention 'Wikipedia', 'WikiProject', 'Talk', 'Draft', or page names. "
        "Return a JSON array of strings only."
    )
    system = f"You output strictly valid JSON. Headlines follow rules:\n{rules}"
    user = textwrap.dedent(f"""
        Mood: {mood.upper()}
        Context (cleaned):
        {batch_context(entries)}
    """).strip()
    prompt = f"<<SYS>>{system}<<SYS>>\n\n{user}\n\nReturn the JSON array now."

    # Attempt 1
    content = _call_ollama(prompt, s, temperature=max(0.3, s.temperature * 0.75))
    items = _parse_json_array(content)

    # Attempt 2 (stricter + cooler) if empty
    if not items:
        stricter = prompt + "\nOnly the JSON array; no commentary, no keys."
        content = _call_ollama(stricter, s, temperature=0.3)
        items = _parse_json_array(content)

    # Clean + sanitize + dedupe + cap
    cleaned, seen = [], set()
    for x in items:
        h = clean_headline(x, s.max_words)
        h = sanitize_headline(h)  # drop unsafe headlines entirely
        if not h:
            continue
        k = h.lower()
        if k in seen:
            continue
        seen.add(k)
        cleaned.append(h)
        if len(cleaned) >= n:
            break

    # Fallback if model failed or produced nonsense
    if not cleaned:
        return simple_fallback_headlines(entries, n=n, max_words=s.max_words)
    return cleaned
