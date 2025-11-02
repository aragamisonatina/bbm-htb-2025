# app/llm.py  (drop-in replacement for the per-edit headline function)

import re
import json
import requests
import textwrap
import unicodedata
from typing import Optional
from config import Settings
from cleaning import strip_admin_markup, normalize_title, normalize_comment

# obvious non-headlines we should never accept
BAD_SINGLETONS = {"true", "false", "null", "none", "headline", "ok", "yes", "no"}

def _clean_text_keep_apostrophes(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s or ""))
    s = re.sub(r"\[\[|\]\]|\{|\}|\(|\)|<|>|https?://\S+", " ", s)
    s = s.replace("“"," ").replace("”"," ").replace("«"," ").replace("»"," ").replace('"'," ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def looks_like_headline(text: str, max_words: int = 12, min_words: int = 2) -> bool:
    """Heuristics to ensure the string resembles a human headline."""
    if not text:
        return False
    t = text.strip()
    # reject trivial booleans / placeholders
    if t.lower() in BAD_SINGLETONS:
        return False
    # word count bounds
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", t)
    if not (min_words <= len(words) <= max_words):
        return False
    # require some alphabetic density
    letters = sum(ch.isalpha() for ch in t)
    if letters < max(6, len(t) // 3):
        return False
    return True

def _extractive_fallback(title: str, comment: str, max_words: int = 12) -> str:
    """
    Build a safe, compact fallback headline from title/comment.
    """
    title = normalize_title(title)
    comment = normalize_comment(comment)
    base = title if title else "Article updated"
    # keep it short
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", f"{base} {comment}")
    if not words:
        return base[:60]
    trimmed = " ".join(words[:max_words])
    # capitalise first letter
    return trimmed[0].upper() + trimmed[1:] if trimmed else base

def generate_headline_for_edit(title: str, comment: str, s: Settings) -> str:
    """
    Per-edit: ask for a single plain-text headline (no JSON). Validate and fallback.
    """
    clean_title = normalize_title(title)
    clean_comment = normalize_comment(comment)

    system = (
        "You are a news editor. Based on the following real-time Wikipedia edit, "
        "write one compelling, short news headline (under 12 words). "
        "Do not use quotes or brackets. No emojis."
    )
    user = textwrap.dedent(f"""
        - Article Title: {clean_title or "(untitled)"}
        - Edit Comment: {clean_comment or "No comment"}

        Your response MUST be the headline text and nothing else.
        Do not include any explanations.
    """).strip()

    payload = {
        "model": s.ollama_model,
        "prompt": f"<<SYS>>{system}<<SYS>>\n\n{user}",
        "options": {
            "temperature": max(0.3, getattr(s, "temperature", 0.7) * 0.8),
            "seed": getattr(s, "seed", 42),
            "num_ctx": getattr(s, "num_ctx", 512),
            "num_gpu": getattr(s, "num_gpu", 0),
            "top_p": 0.9,
            "top_k": 40,
        },
        # IMPORTANT: no JSON format for single headline
        "stream": False,
    }

    try:
        r = requests.post(f"{s.ollama_host}/api/generate", json=payload,
                          timeout=getattr(s, "request_timeout_s", 60))
        r.raise_for_status()
        text = r.json().get("response", "") or ""
    except Exception:
        # if the call itself fails, return fallback
        return _extractive_fallback(title, comment, max_words=getattr(s, "max_words", 12))

    # Clean model output
    text = _clean_text_keep_apostrophes(text)

    # Take the first non-empty line, model sometimes includes stray lines
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")

    # Final guards: strip surrounding quotes/brackets + validate
    first_line = first_line.strip().strip("'").strip('"').strip("[](){}")
    if not looks_like_headline(first_line, max_words=getattr(s, "max_words", 12)):
        return _extractive_fallback(title, comment, max_words=getattr(s, "max_words", 12))

    # Capitalize first letter (light touch)
    return first_line[0].upper() + first_line[1:]
