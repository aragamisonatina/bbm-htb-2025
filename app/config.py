# app/config.py
"""
Centralized configuration and shared lexicons.

- `Settings` holds all runtime knobs (batch length, LLM model, thresholds).
- `STOPWORDS` and `ADMIN_TERMS` are removed from topic scoring so they don't
  dominate clustering or headline wording.
"""

from dataclasses import dataclass


# -----------------------------------------------------------------------------
# Runtime settings
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    # Streaming / batch windows
    stream_url: str = "https://stream.wikimedia.org/v2/stream/mediawiki.recentchange"
    batch_seconds: int = 15                 # rolling window length (s)
    enwiki_only: bool = True                # filter to English Wikipedia

    # Headline targets
    top_headlines: int = 10                 # max distinct headlines to print
    max_words: int = 8                      # hard cap for headline length

    # Clustering thresholds
    jaccard_threshold: float = 0.69         # token Jaccard (lower => more merging)
    phrasal_fuse_threshold: float = 0.90    # difflib ratio for near-duplicate phrases

    # Safety: avoid calling the LLM on tiny/noisy windows
    min_edits_for_llm: int = 16             # fallback to extractive if fewer

    # LLM backend (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"
    temperature: float = 0.7                # general default; per-call may override
    seed: int = 42
    num_ctx: int = 512                      # CPU-safe context
    num_gpu: int = 0                        # 0 => force CPU on modest machines

    # Networking / retries
    request_timeout_s: int = 60             # HTTP request timeout
    sse_retry_base_s: int = 3               # initial backoff when 429/connection error
    sse_retry_max_s: int = 20               # cap backoff


# -----------------------------------------------------------------------------
# Shared lexicons
# -----------------------------------------------------------------------------

# High-frequency content words we *don’t* want to bias clustering/scoring.
STOPWORDS = {
    "wikipedia", "wikiproject", "project", "article", "articles",
    "editor", "editors", "edited", "update", "updates", "revised",
    "revision", "page", "pages", "talk", "section", "content",
    "reference", "references", "citation", "citations", "category",
    "categories", "template", "templates",
}

# Admin/process vocabulary we strip from similarity and phrasing.
ADMIN_TERMS = {
    "talk", "draft", "notification", "redirects", "discussion",
    "rfd", "afd", "template", "category", "wikidata", "citation",
    "references", "log", "banner",
}
