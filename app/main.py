# app/main.py
"""
Entry point: roll fixed windows, summarize mood, call LLM once per window,
score + dedupe, print up to K distinct headlines.
"""

import logging
import argparse
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import Settings
from stream import event_generator, collect_window
from llm import generate_batch_headlines
from scoring import (
    term_maps,
    score_headline_blend,
    cluster_and_merge,
    fuse_phrasal_near_dupes,
    simple_fallback_headlines,
)

log = logging.getLogger(__name__)


def _window_mood(batch) -> str:
    """Compute window mood via VADER compound average."""
    sent = SentimentIntensityAnalyzer()
    scores = [sent.polarity_scores(e.get("comment") or e.get("title"))["compound"] for e in batch]
    avg = (sum(scores) / max(1, len(scores)))
    return "positive" if avg > 0.2 else "negative" if avg < -0.2 else "neutral"


def _entries_from_batch(batch):
    """Transform raw stream events to the minimal payload the LLM expects."""
    return [{"title": e.get("title", ""), "comment": e.get("comment", ""), "delta": e.get("delta", 0)} for e in batch]


def _print_headlines(items):
    """Pretty printer for the final selection."""
    if not items:
        print("   (no distinct topics this window)")
        return
    print("📰 Headlines:")
    for rep, total, _members in items:
        print(f" → ({rep}, {total})")


def run(settings: Settings):
    """Run rolling windows; generate up to K distinct headlines per window."""
    nltk.download("vader_lexicon", quiet=True)
    gen = event_generator(settings)
    print(f"🔁 Rolling windows of {settings.batch_seconds}s. Ctrl+C to stop.")

    while True:
        batch = collect_window(gen, settings.batch_seconds)
        print(f"\n⏱️  Batch window: {settings.batch_seconds}s  – collected {len(batch)} edits")
        if not batch:
            print("   (no events this window)")
            continue

        mood = _window_mood(batch)
        print(f"   mood: {mood.upper()}")

        # If too small/noisy, avoid LLM and fall back deterministically.
        if len(batch) < getattr(settings, "min_edits_for_llm", 12):
            print("   (too few edits for LLM — using extractive fallback)")
            entries = _entries_from_batch(batch)
            fallbacks = simple_fallback_headlines(entries, n=settings.top_headlines, max_words=settings.max_words)
            # score + package for printing
            tbytes, tcounts = term_maps(batch)
            scored = [(h, score_headline_blend(h, tbytes, tcounts)) for h in fallbacks]
            clusters = cluster_and_merge(scored, settings.jaccard_threshold)
            clusters = fuse_phrasal_near_dupes(clusters, getattr(settings, "phrasal_fuse_threshold", 0.88))
            _print_headlines(clusters[:settings.top_headlines])
            continue

        # Ask the model for more than we need; we'll prune to distinct topics.
        entries = _entries_from_batch(batch)
        want = settings.top_headlines * 2
        try:
            candidates = generate_batch_headlines(entries, mood, settings, want)
        except Exception as e:
            print(f"   🚫 Llama error: {e}")
            # fallback path ensures we still show something
            fallbacks = simple_fallback_headlines(entries, n=settings.top_headlines, max_words=settings.max_words)
            tbytes, tcounts = term_maps(batch)
            scored = [(h, score_headline_blend(h, tbytes, tcounts)) for h in fallbacks]
            clusters = cluster_and_merge(scored, settings.jaccard_threshold)
            clusters = fuse_phrasal_near_dupes(clusters, getattr(settings, "phrasal_fuse_threshold", 0.88))
            _print_headlines(clusters[:settings.top_headlines])
            continue

        # Score (bytes+freq), cluster by tokens, fuse phrasing near-dupes, cap to K.
        tbytes, tcounts = term_maps(batch)
        scored = [(h, score_headline_blend(h, tbytes, tcounts, blend=0.80)) for h in candidates]
        clusters = cluster_and_merge(scored, settings.jaccard_threshold)
        clusters = fuse_phrasal_near_dupes(clusters, getattr(settings, "phrasal_fuse_threshold", 0.88))
        _print_headlines(clusters[:settings.top_headlines])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=Settings().batch_seconds, help="Window length in seconds")
    p.add_argument("--headlines", type=int, default=Settings().top_headlines, help="Max distinct headlines to print")
    p.add_argument("--max-words", type=int, default=Settings().max_words, help="Headline hard word cap")
    p.add_argument("--jaccard", type=float, default=Settings().jaccard_threshold, help="Token Jaccard threshold")
    p.add_argument("--phrasal", type=float, default=Settings().phrasal_fuse_threshold, help="Phrasal fuse threshold")
    p.add_argument("--min-llm", type=int, default=Settings().min_edits_for_llm, help="Min edits before using LLM")
    args = p.parse_args()

    s = Settings(
        batch_seconds=args.seconds,
        top_headlines=args.headlines,
        max_words=args.max_words,
        jaccard_threshold=args.jaccard,
        phrasal_fuse_threshold=args.phrasal,
        min_edits_for_llm=args.min_llm,
    )
    run(s)
