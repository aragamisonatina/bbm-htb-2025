# ==== Live Wikipedia Edits → Rolling Llama Headlines (Ollama, CPU-safe windows) ====

import os
import re
import json
import time
import textwrap
import requests
import pandas as pd
import nltk
from requests_sse import EventSource
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from collections import Counter
from datetime import datetime

# -------- Config --------
STREAM_URL    = "https://stream.wikimedia.org/v2/stream/mediawiki.recentchange"
OLLAMA_HOST   = "http://localhost:11434"
OLLAMA_MODEL  = "llama3.2:1b"      # tiny model
BATCH_SECONDS = 15                  # <-- change this to adjust window length
TOP_HEADLINES = 10

# Minimal gating; keep it loose so we always get data
ENWIKI_ONLY       = True
STOPWORDS = {
    "wikipedia","wikiproject","project","article","articles","editor","editors","edited",
    "update","updates","revised","revision","page","pages","talk","section","content",
    "reference","references","citation","citations","category","categories","template","templates"
}

# -------- Setup --------
nltk.download("vader_lexicon", quiet=True)
analyzer = SentimentIntensityAnalyzer()

# -------- Helpers to compute byte delta from event --------
def _size_delta(change: dict) -> int:
    """Return absolute byte change for the edit if available, else 0."""
    length = change.get("length") or {}
    old = length.get("old"); new = length.get("new")
    if isinstance(old, int) and isinstance(new, int):
        return abs(new - old)
    rev = change.get("revision") or {}
    osz = (rev.get("old") or {}).get("size")
    nsz = (rev.get("new") or {}).get("size")
    if isinstance(osz, int) and isinstance(nsz, int):
        return abs(nsz - osz)
    return 0

# -------- Minimal stream (no heavy filters, time-boxed) --------
def collect_for(seconds=BATCH_SECONDS):
    """Collect ANY recent changes for a fixed time window (nearly no filtering)."""
    headers = {"User-Agent": "HTB-Headlines/1.0 (demo)", "Accept": "text/event-stream"}
    edits = []
    start = time.time()
    try:
        with EventSource(STREAM_URL, headers=headers) as stream:
            for event in stream:
                if time.time() - start >= seconds:
                    break
                if event.type != "message" or not event.data:
                    continue
                try:
                    change = json.loads(event.data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(change, dict):
                    continue
                if ENWIKI_ONLY and change.get("wiki") != "enwiki":
                    continue

                title = str(change.get("title", "") or "").strip()
                comment = str(change.get("comment", "") or "").strip()
                delta = _size_delta(change)

                edits.append({
                    "user": change.get("user", ""),
                    "title": title,
                    "comment": comment,
                    "timestamp": change.get("timestamp", 0),
                    "delta": int(delta),
                })
    except Exception as e:
        print(f"⚠️ stream error: {e}")

    return pd.DataFrame(edits, columns=["user","title","comment","timestamp","delta"])

# -------- Cleaning helpers --------
ADMIN_TERMS = {
    "talk", "draft", "notification", "redirects", "discussion", "rfd", "afd",
    "template", "category", "wikidata", "citation", "references", "log", "banner"
}
BAN_TERMS = {"wikipedia", "wikiproject", "wikiprojects", "talk:", "draft talk:", "[[", "]]", "redirects for discussion"}

def _strip_admin_markup(text: str) -> str:
    t = str(text)
    t = re.sub(r"\b(Talk|Draft talk|Draft|User talk|Category|Template):", "", t, flags=re.I)
    t = re.sub(r"\[\[|\]\]|\{{2,}|\}{2,}", "", t)
    t = re.sub(r"http[s]?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _clean_headline(h):
    h = _strip_admin_markup(h)
    h = re.sub(r"^[\-\•\s]+", "", h).strip().strip('“”\"\' ').rstrip(".")
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\bwikiprojects?\b", "projects", h, flags=re.I)
    h = re.sub(r"\bwikipedia\b", "the encyclopedia", h, flags=re.I)
    h = re.sub(r"\btalk:\b", "", h, flags=re.I)
    h = re.sub(r"\bredirects?\b.*", "", h, flags=re.I)
    words = h.split()
    return (" ".join(words[:12]) if len(words) > 12 else h).strip(" -:").strip()

def _looks_like_headline(h):
    if not h or len(h.split()) < 2 or len(h) < 8:
        return False
    low = h.lower()
    if any(b in low for b in BAN_TERMS):
        return False
    if re.search(r"\b(notification|discussion|rfd|afd|banner|log)\b", low):
        return False
    return True

# -------- Batch summarization + ONE Llama call --------
def _batch_context(entries, max_chars=600):
    # summarize the whole window
    words, examples = [], []
    for e in entries[:8]:
        txt = _strip_admin_markup(e["text"])
        examples.append((txt[:140] + "...") if len(txt) > 140 else txt)
        for w in re.findall(r"\b[a-zA-Z]{5,}\b", txt):
            wl = w.lower()
            if wl not in STOPWORDS and wl not in ADMIN_TERMS:
                words.append(wl)
    common = ", ".join([w for w,_ in Counter(words).most_common(15)])
    blob = f"Common terms: {common}\nExamples:\n- " + "\n- ".join(examples)
    return blob[:max_chars]

def llama_headlines_batch(entries, mood, n=TOP_HEADLINES):
    """ONE call to Llama to produce n headlines for the whole window."""
    system = (
        "Write concise, newsroom-style headlines summarizing patterns in recent edits. "
        "Strict rules: present tense; ≤12 words; no clickbait; DO NOT mention "
        "'Wikipedia', 'WikiProject', 'Talk', 'Draft', 'Redirects for discussion', or page names. "
        "Output MUST be a JSON array of strings ONLY (no markdown, no keys, no commentary)."
    )
    user = textwrap.dedent(f"""
        Mood: {mood.upper()}
        Context (cleaned of admin chatter):
        {_batch_context(entries)}

        Return exactly {n} distinct headline options as a JSON array of strings. No extra text.
    """).strip()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"<<SYS>>{system}<<SYS>>\n\n{user}",
        "options": {"temperature": 0.7, "seed": 42, "num_ctx": 512, "num_gpu": 0},
        "stream": False
    }

    r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:400]}")
    content = r.json().get("response", "").strip()

    m = re.search(r"\[.*\]", content, re.S)
    raw = []
    if m:
        try:
            arr = json.loads(m.group(0))
            raw = [str(x) for x in arr if isinstance(x, (str,int,float))]
        except json.JSONDecodeError:
            pass
    if not raw:
        raw = [ln.strip() for ln in content.splitlines() if ln.strip()]

    cleaned, seen = [], set()
    for x in raw:
        h = _clean_headline(x)
        if not _looks_like_headline(h): continue
        kl = h.lower()
        if kl in seen: continue
        seen.add(kl)
        cleaned.append(h)
        if len(cleaned) >= n: break
    return cleaned

# -------- One batch → headlines (with byte-weighted scores) --------
def run_batch(seconds=BATCH_SECONDS):
    print(f"\n⏱️  Batch window: {seconds}s  ({datetime.now().strftime('%H:%M:%S')})")
    df = collect_for(seconds=seconds)
    print(f"   collected {len(df)} edits")

    if df.empty:
        print("   (no events this window)")
        return

    # Build entries and mood
    entries, sentiments = [], []
    for _, row in df.iterrows():
        title = str(row["title"])
        edit  = str(row["comment"])
        delta = int(row.get("delta", 0))
        full_text = f"{title.strip()}: {edit.strip()}"
        sentiments.append(analyzer.polarity_scores(edit)["compound"])
        entries.append({"text": full_text, "delta": delta})

    avg_sentiment = sum(sentiments) / max(1, len(sentiments))
    mood = "positive" if avg_sentiment > 0.2 else "negative" if avg_sentiment < -0.2 else "neutral"
    print(f"   mood: {mood.upper()}")

    # Build a term → total_bytes map from the window
    term_bytes = Counter()
    for e in entries:
        txt = _strip_admin_markup(e["text"])
        delta = int(e["delta"])
        for w in re.findall(r"\b[a-zA-Z]{3,}\b", txt):
            wl = w.lower()
            if wl in STOPWORDS or wl in ADMIN_TERMS:
                continue
            term_bytes[wl] += max(0, delta)

    # Generate headlines (one call)
    print("📰 Headlines:")
    try:
        headlines = llama_headlines_batch(entries, mood, n=TOP_HEADLINES)

        def score_headline(h: str) -> int:
            # Sum bytes for all words in the headline
            s = 0
            for w in re.findall(r"\b[a-zA-Z]{3,}\b", h.lower()):
                if w in STOPWORDS or w in ADMIN_TERMS:
                    continue
                s += term_bytes.get(w, 0)
            return int(s)

        # Emit as tuples: (Title, bytes)
        scored = [(h, score_headline(h)) for h in headlines]
        # If you want them sorted by bytes desc:
        scored.sort(key=lambda t: t[1], reverse=True)

        for h, b in scored:
            print(f" → ({h}, {b})")
    except Exception as e:
        print(f"   🚫 Llama error: {e}")

# -------- Main loop --------
print(f"🔁 Starting rolling windows of {BATCH_SECONDS}s. Press Ctrl+C to stop.")
while True:
    run_batch(BATCH_SECONDS)
