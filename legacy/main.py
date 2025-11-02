# ==== Minimal Wikipedia Edits → Llama Headlines (Ollama only, CPU-safe) ====

import os
import re
import json
import random
import textwrap
import requests
import pandas as pd
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from collections import Counter, defaultdict

# ---------- Config ----------
CSV_PATH = "htb_new_edits.csv"
OLLAMA_HOST  = "http://localhost:11434"   # Ollama default
OLLAMA_MODEL = "llama3.2:1b"              # tiny model -> low RAM/CPU friendly
N_HEADLINES  = 3
TOP_KEYWORDS = 8
MIN_CLUSTER  = 2

STOPWORDS = {
    "wikipedia","wikiproject","project","article","articles","editor","editors","edited",
    "update","updates","revised","revision","page","pages","talk","section","content",
    "reference","references","citation","citations","category","categories","template","templates"
}

# ---------- Setup ----------
nltk.download("vader_lexicon", quiet=True)
analyzer = SentimentIntensityAnalyzer()

# ---------- Load + collect ----------
df = pd.read_csv(CSV_PATH, encoding="latin1")

entries, all_keywords = [], []
for _, row in df.iterrows():
    title = str(row["Title"])
    edit  = str(row["Comment"])
    full_text = f"{title.strip()}: {edit.strip()}"

    sentiment = analyzer.polarity_scores(edit)["compound"]

    raw = re.findall(r"\b[a-zA-Z]{5,}\b", full_text.lower())
    keywords = [w for w in raw if w not in STOPWORDS]
    all_keywords.extend(keywords)

    entries.append({"text": full_text, "sentiment": sentiment, "keywords": keywords})

# ---------- Mood ----------
avg_sentiment = sum(e["sentiment"] for e in entries) / max(1, len(entries))
general_mood = "positive" if avg_sentiment > 0.2 else "negative" if avg_sentiment < -0.2 else "neutral"
print(f"\n🧠 Wikipedia's current mood: {general_mood.upper()}")

# ---------- Hot topics ----------
keyword_counts = Counter(all_keywords)
top_keywords = [kw for kw, _ in keyword_counts.most_common(TOP_KEYWORDS)]

# ---------- Cluster by topic ----------
topic_clusters = defaultdict(list)
for entry in entries:
    matched = False
    for kw in entry["keywords"]:
        if kw in top_keywords:
            topic_clusters[kw].append(entry)
            matched = True
    if not matched:
        topic_clusters["misc"].append(entry)

# ---------- Llama helpers (clean context + strict postprocess) ----------
ADMIN_TERMS = {
    "talk", "draft", "notification", "redirects", "discussion", "rfd", "afd",
    "template", "category", "wikidata", "citation", "references", "log", "banner"
}
BAN_TERMS = {"wikipedia", "wikiproject", "wikiprojects", "talk:", "draft talk:", "[[", "]]", "redirects for discussion"}

def _strip_admin_markup(text: str) -> str:
    t = str(text)
    # remove page namespace prefixes and wiki markup
    t = re.sub(r"\b(Talk|Draft talk|Draft|User talk|Category|Template):", "", t, flags=re.I)
    t = re.sub(r"\[\[|\]\]|\{{2,}|\}{2,}", "", t)
    t = re.sub(r"http[s]?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _tiny_context(items, max_chars=280):
    # Build context that avoids admin chatter
    words = []
    examples = []
    for e in items[:5]:
        txt = _strip_admin_markup(e["text"])
        examples.append((txt[:140] + "...") if len(txt) > 140 else txt)
        for w in re.findall(r"\b[a-zA-Z]{5,}\b", txt):
            wl = w.lower()
            if wl not in STOPWORDS and wl not in ADMIN_TERMS:
                words.append(wl)
    common = ", ".join([w for w,_ in Counter(words).most_common(10)])
    blob = f"Common terms: {common}\nExamples:\n- " + "\n- ".join(examples)
    return blob[:max_chars]

def _clean_headline(h):
    h = _strip_admin_markup(h)
    h = re.sub(r"^[\-\•\s]+", "", h).strip().strip('“”\"\' ').rstrip(".")
    h = re.sub(r"\s+", " ", h)
    # ban terms
    h = re.sub(r"\bwikiprojects?\b", "projects", h, flags=re.I)
    h = re.sub(r"\bwikipedia\b", "the encyclopedia", h, flags=re.I)
    h = re.sub(r"\btalk:\b", "", h, flags=re.I)
    h = re.sub(r"\bredirects?\b.*", "", h, flags=re.I)  # nuke “redirects for discussion …”
    # keep it short
    words = h.split()
    h = " ".join(words[:12]) if len(words) > 12 else h
    return h.strip(" -:").strip()

def _looks_like_headline(h):
    if not h or len(h.split()) < 2 or len(h) < 8:
        return False
    low = h.lower()
    if any(b in low for b in BAN_TERMS):
        return False
    if re.search(r"\b(notification|discussion|rfd|afd|banner|log)\b", low):
        return False
    return True

def _score(h, topic_hint=""):
    s = 0
    # brevity
    s += max(0, 12 - len(h.split()))
    # starts with capital letter word (headline-y)
    s += 1 if re.match(r"^[A-Z]", h) else 0
    # includes hint
    if topic_hint and topic_hint.lower() in h.lower():
        s += 2
    return s

def _topic_hint(items):
    bag = Counter(
        w.lower()
        for e in items
        for w in re.findall(r"\b[a-zA-Z]{5,}\b", _strip_admin_markup(e["text"]))
        if w.lower() not in STOPWORDS and w.lower() not in ADMIN_TERMS
    )
    for w,_ in bag.most_common(1):
        return w
    return ""

def llama_headlines_ollama(topic, items, mood, n=N_HEADLINES):
    system = (
        "Write concise, newsroom-style headlines summarizing user activity patterns."
        " Strict rules: present tense; ≤12 words; no clickbait; DO NOT mention"
        " 'Wikipedia', 'WikiProject', 'Talk', 'Draft', 'Redirects for discussion', or page names."
        " Output MUST be a JSON array of strings ONLY (no markdown, no keys, no commentary)."
    )
    user = textwrap.dedent(f"""
        Mood: {mood.upper()}
        Topic: {topic}
        Context (cleaned of admin chatter):
        {_tiny_context(items)}

        Return exactly {n} headline options as a JSON array of strings. No extra text.
    """).strip()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"<<SYS>>{system}<<SYS>>\n\n{user}",
        "options": {
            "temperature": 0.7,
            "seed": 42,
            "num_ctx": 512,
            "num_gpu": 0
        },
        "stream": False
    }

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=60)
    except requests.exceptions.ConnectionError:
        raise RuntimeError(f"Ollama not reachable at {OLLAMA_HOST}. Is the service running?")

    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:400]}")

    content = r.json().get("response", "").strip()

    # Parse JSON array if present, otherwise split lines
    m = re.search(r"\[.*\]", content, re.S)
    raw = []
    if m:
        try:
            arr = json.loads(m.group(0))
            raw = [str(x) for x in arr if isinstance(x, (str,int,float))]
        except json.JSONDecodeError:
            raw = []
    if not raw:
        raw = [ln.strip() for ln in content.splitlines() if ln.strip()]

    # Clean, filter, rank, dedupe
    hint = _topic_hint(items)
    cleaned = []
    seen = set()
    for x in raw:
        h = _clean_headline(x)
        if not _looks_like_headline(h):
            continue
        key = h.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(h)

    cleaned.sort(key=lambda s: _score(s, hint), reverse=True)
    return cleaned[:n]


# ---------- Generate headlines ----------
print("\n📰 WIKIPEDIA'S HEADLINES (LLM via Ollama, CPU-safe):")
for topic, items in topic_clusters.items():
    if len(items) < MIN_CLUSTER:
        continue
    try:
        for h in llama_headlines_ollama(topic, items, general_mood, n=N_HEADLINES):
            print("→", h)
    except Exception as e:
        print(f"🚫 Llama error for topic '{topic}': {e}")
