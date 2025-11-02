# app/scoring.py
"""
Scoring, clustering, and deduping utilities for headlines.

Includes:
- term_maps(): build byte and frequency maps from a window
- score_headline_blend(): blended score (bytes + frequency) to avoid zero walls
- cluster_and_merge(): token Jaccard clustering (unigram + bigram)
- fuse_phrasal_near_dupes(): phrasal (difflib) near-duplicate fusion
- mmr_select(): optional diversity-aware selection
- simple_fallback_headlines(): deterministic extractive backup
"""

import re
import difflib
import unicodedata
from typing import List, Tuple, Dict, Callable
from collections import Counter

from config import STOPWORDS, ADMIN_TERMS
from cleaning import strip_admin_markup, words_for_similarity

# ---------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------

RE_WORDS3 = re.compile(r"\b[a-zA-Z]{3,}\b", re.UNICODE)
RE_ASCII_APOS = re.compile(r"[^A-Za-z0-9' ]+")

# ---------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------

def _tokens(text: str):
    """Yield normalized tokens (len>=3) minus stop/admin words."""
    for w in RE_WORDS3.findall(text.lower()):
        if w not in STOPWORDS and w not in ADMIN_TERMS:
            yield w

# ---------------------------------------------------------------------
# Term maps & scoring
# ---------------------------------------------------------------------

def term_maps(entries: List[Dict]) -> Tuple[Counter, Counter]:
    """
    Build (term_bytes, term_counts) across the window.
    term_bytes[w]: sum of byte deltas for edits mentioning w
    term_counts[w]: raw token frequency across edits
    """
    tbytes, tcounts = Counter(), Counter()
    for e in entries:
        delta = max(0, int(e.get("delta", 0)))
        txt = strip_admin_markup(f'{e.get("title","")} {e.get("comment","")}')
        toks = list(_tokens(txt))
        for w in toks:
            tcounts[w] += 1
            tbytes[w] += delta
    return tbytes, tcounts


def _unit_scale(term_bytes: Counter, term_counts: Counter) -> int:
    """Average bytes per token occurrence across the window (>=1)."""
    total_b = sum(term_bytes.values())
    total_c = sum(term_counts.values())
    return max(1, total_b // max(1, total_c))


def score_headline_blend(headline: str,
                         term_bytes: Counter,
                         term_counts: Counter,
                         blend: float = 0.80) -> int:
    """
    Blend bytes + frequency so sparse windows don't score as zeros.
    score = blend*bytes_overlap + (1-blend)*freq_overlap*unit_scale
    """
    b = sum(term_bytes.get(w, 0) for w in _tokens(headline))
    c = sum(term_counts.get(w, 0) for w in _tokens(headline))
    return int(blend * b + (1.0 - blend) * c * _unit_scale(term_bytes, term_counts))

# ---------------------------------------------------------------------
# Clustering & diversity
# ---------------------------------------------------------------------

def jaccard_tokens(a: str, b: str) -> float:
    """Jaccard similarity of unigram+bigram token sets."""
    A, B = words_for_similarity(a), words_for_similarity(b)
    if not A and not B: return 1.0
    if not A or not B:  return 0.0
    return len(A & B) / len(A | B)


def cluster_and_merge(scored: List[Tuple[str, int]],
                      sim_thresh: float = 0.55) -> List[Tuple[str, int, List[Tuple[str, int]]]]:
    """
    Group near-duplicate headlines by token Jaccard.
    Returns [(representative, total_score, members[(h,score)])], sorted desc.
    """
    clusters: List[Dict] = []
    for h, s in scored:
        tok = words_for_similarity(h)
        best_sim, best_idx = 0.0, -1
        for i, c in enumerate(clusters):
            inter = len(tok & c["tok"]); union = len(tok | c["tok"]) or 1
            sim = inter / union
            if sim > best_sim:
                best_sim, best_idx = sim, i
        if best_sim >= sim_thresh and best_idx >= 0:
            c = clusters[best_idx]
            c["tok"] |= tok
            c["sum"] += s
            c["items"].append((h, s))
            if s > c["best"]:
                c["best"], c["repr"] = s, h
        else:
            clusters.append({"tok": set(tok), "sum": s, "best": s, "repr": h, "items": [(h, s)]})
    merged = [(c["repr"], c["sum"], c["items"]) for c in clusters]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


def _norm_for_fuzzy(s: str) -> str:
    """
    Normalize a string for phrasal fuzzy matching:
    - strip accents, keep ascii letters/numbers/apostrophes/spaces
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = RE_ASCII_APOS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def fuse_phrasal_near_dupes(
    clusters: List[Tuple[str, int, List[Tuple[str, int]]]],
    threshold: float = 0.88
) -> List[Tuple[str, int, List[Tuple[str, int]]]]:
    """
    Merge clusters whose representative lines are phrasal near-duplicates.
    Useful after token clustering to collapse paraphrases.
    """
    fused: List[Dict] = []
    for rep, score, members in clusters:
        key = _norm_for_fuzzy(rep)
        placed = False
        for f in fused:
            if difflib.SequenceMatcher(None, key, f["key"]).ratio() >= threshold:
                f["score"] += score
                f["members"].extend(members)
                if score > f["best"]:
                    f["best"], f["rep"] = score, rep
                placed = True
                break
        if not placed:
            fused.append({"key": key, "rep": rep, "score": score, "best": score, "members": list(members)})
    fused.sort(key=lambda x: x["score"], reverse=True)
    return [(f["rep"], f["score"], f["members"]) for f in fused]


def mmr_select(
    candidates: List[Tuple[str, int]],
    k: int = 10,
    sim_fn: Callable[[str, str], float] = jaccard_tokens,
    lambda_div: float = 0.75
) -> List[Tuple[str, int]]:
    """
    Maximal Marginal Relevance: balance relevance (score) vs. diversity.
    lambda_div: 1.0 -> pure relevance, 0.0 -> pure diversity.
    """
    selected: List[Tuple[str, int]] = []
    pool = sorted(candidates, key=lambda t: t[1], reverse=True)
    while pool and len(selected) < k:
        best, best_val = None, -1e9
        for h, s in pool:
            redundancy = max((sim_fn(h, sh) for sh, _ in selected), default=0.0)
            val = lambda_div * s - (1 - lambda_div) * redundancy * s
            if val > best_val:
                best, best_val = (h, s), val
        selected.append(best)
        pool.remove(best)
    return selected

# ---------------------------------------------------------------------
# Extractive fallback (never empty)
# ---------------------------------------------------------------------

def simple_fallback_headlines(entries: List[Dict], n: int = 10, max_words: int = 8) -> List[str]:
    """
    Deterministic backup when the model fails:
    pick top frequent content terms and chunk them into short phrases.
    """
    bag = Counter()
    samples: List[str] = []
    for e in entries[:12]:
        txt = strip_admin_markup(f'{e.get("title","")} {e.get("comment","")}')
        samples.append(txt)
        for w in RE_WORDS3.findall(txt.lower()):
            if len(w) >= 4 and w not in STOPWORDS and w not in ADMIN_TERMS:
                bag[w] += 1
    tops = [w.title() for w, _ in bag.most_common(60)]
    out: List[str] = []
    i = 0
    while len(out) < n and i < len(tops):
        chunk = " ".join(tops[i:i + max_words]).strip()
        if chunk:
            out.append(chunk)
        i += max_words
    if not out:  # absolute last resort: sample snippets
        out = [s[:60] for s in samples if s][:n]
    return out

# ---------------------------------------------------------------------
# Legacy byte-only helpers (still used by older paths)
# ---------------------------------------------------------------------

def byte_term_map(entries: List[Dict]) -> Counter:
    """Sum bytes per term for the window (legacy scoring)."""
    term_bytes = Counter()
    for e in entries:
        delta = max(0, int(e.get("delta", 0)))
        txt = strip_admin_markup(f'{e.get("title","")} {e.get("comment","")}')
        for w in RE_WORDS3.findall(txt.lower()):
            if w not in STOPWORDS and w not in ADMIN_TERMS:
                term_bytes[w] += delta
    return term_bytes


def score_headline(headline: str, term_bytes: Counter) -> int:
    """Legacy: sum window bytes for all tokens present in the headline."""
    score = 0
    for w in RE_WORDS3.findall(headline.lower()):
        if w not in STOPWORDS and w not in ADMIN_TERMS:
            score += term_bytes.get(w, 0)
    return int(score)
