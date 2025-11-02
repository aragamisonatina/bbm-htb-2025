# app/cleaning.py
"""
Lightweight text normalization helpers used by the streaming pipeline.

Design goals:
- Keep functions short and predictable (≤ 20 lines each).
- Normalize aggressively for clustering/scoring, but leave display-quality
  handling (diacritics, apostrophes) to the LLM post-cleaner.
- Remove wiki/markup noise and high-churn admin terms so topics cluster better.
"""

import re
from typing import Set
from config import STOPWORDS, ADMIN_TERMS

# ---------------------------------------------------------------------------
# Constants & compiled patterns
# ---------------------------------------------------------------------------

# Namespaces we strip from the *start* of titles (e.g., "Talk:Page" → "Page")
NS_PREFIXES: Set[str] = {
    "special", "user", "user talk", "talk", "wikipedia", "file", "template",
    "help", "category", "portal", "book", "draft", "timedtext", "module",
    "mediawiki",
}

# Tokens we never want to influence similarity/scoring
EXCLUDE_TOKENS: Set[str] = {"whatlinkshere", "special", "category", "categories", "wp"}

# Precompiled regexes for speed & clarity
RE_LINKS = re.compile(r"\[\[|\]\]|\{\{|\}\}")
RE_URL = re.compile(r"http[s]?://\S+")
RE_SPACES = re.compile(r"\s+")
RE_NS = re.compile(r"^([^:]+):(.*)$")
RE_NONLET_ASCII = re.compile(r"[^A-Za-z ]+")  # scoring-only: ASCII letters & spaces

# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------

def _collapse_spaces(s: str) -> str:
    """Normalize whitespace to single spaces and strip ends."""
    return RE_SPACES.sub(" ", s).strip()

def _ascii_words_only(s: str) -> str:
    """
    Keep ASCII letters and spaces only (for clustering/scoring).
    NOTE: Display cleanup that preserves diacritics lives in llm.py.
    """
    return _collapse_spaces(RE_NONLET_ASCII.sub(" ", s))

def _drop_excluded_tokens(text: str) -> str:
    """Remove EXCLUDE_TOKENS that bias clustering (e.g., 'category')."""
    parts = [w for w in text.split() if w.lower() not in EXCLUDE_TOKENS]
    return " ".join(parts)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """
    Strip namespace prefixes, slashes, markup; return ASCII word soup
    suited for topic clustering (NOT for display).
    """
    t = (title or "").strip()
    m = RE_NS.match(t)
    if m and m.group(1).lower() in NS_PREFIXES:
        t = m.group(2)
    t = t.replace("/", " ")
    t = _ascii_words_only(t)
    return _drop_excluded_tokens(t)

def normalize_comment(comment: str) -> str:
    """
    Remove wiki links/URLs and admin noise; return ASCII words for scoring.
    """
    c = RE_LINKS.sub(" ", comment or "")
    c = RE_URL.sub(" ", c)
    c = _ascii_words_only(c)
    return _drop_excluded_tokens(c)

def strip_admin_markup(text: str) -> str:
    """
    Remove links/URLs/extra spaces but do NOT drop letters (used to create
    previews for the LLM; display-safe).
    """
    t = RE_LINKS.sub(" ", text or "")
    t = RE_URL.sub(" ", t)
    return _collapse_spaces(t)

def words_for_similarity(text: str) -> Set[str]:
    """
    Build a token set (unigrams + bigrams) for Jaccard clustering.
    - Lowercased, ASCII-only words with length ≥ 4.
    - Excludes STOPWORDS and ADMIN_TERMS on the unigram head.
    """
    t = strip_admin_markup(text.lower())
    words = [w for w in RE_NONLET_ASCII.sub(" ", t).split() if len(w) >= 4]
    grams: Set[str] = set(words)
    grams |= {f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)}
    return {
        g for g in grams
        if g.split("_", 1)[0] not in STOPWORDS
        and g.split("_", 1)[0] not in ADMIN_TERMS
    }
