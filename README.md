# bbm-htb-2025 - "Project Prince"

**Project Prince** is a real-time pipeline that converts Wikimedia’s RecentChanges stream into concise, newsroom-style headlines using a local Llama model (via Ollama). Every configurable window (default 15s), it ingests live edits, normalizes titles and comments, removes wiki/admin noise (namespaces, links, boilerplate), and builds a compact context for the model. Candidate headlines are cleaned (≤8 words, natural phrases, apostrophes/diacritics preserved), scored by a blend of byte-change and term frequency from the window, and then deduplicated with token-set Jaccard and phrasal (difflib) merging. The result is a set of distinct, high-signal headlines with integer “heat” scores that reflect topical activity in the current window, with a deterministic extractive fallback to ensure output even if the model misbehaves. Configuration covers window length, headline count, word cap, clustering thresholds, and model settings.

<br>

## Developers
- aragamisonatina
- beppermon
- GStern05
- mostafam99
- samad-a

<br>

## Requirements
- This application uses **Llama 3.2**. Install Ollama [here](https://ollama.com/download).
- Before you run this program, open Windows PowerShell and type `ollama pull llama3.2:1b`. You may close this afterwards.
- Enjoy!

<br>

## Tools Used
- Python 3.11
- Llama 3.2:1b (generation)
- ChatGPT / Github CoPilot (logic and coding guidance)

<br>

# API Reference / Cheatsheet

This document lists **every public constant, function, and class** in the `app/` codebase with concise descriptions.

---

## `app/config.py` - global settings and shared word lists
### Class: `Settings` (frozen dataclass)

| Field | Type | Default | Description |
|---|---|---:|---|
| `stream_url` | `str` | `"https://stream.wikimedia.org/v2/stream/mediawiki.recentchange"` | Wikimedia RecentChanges SSE endpoint. |
| `batch_seconds` | `int` | `15` | Rolling collection window length in seconds. |
| `enwiki_only` | `bool` | `True` | If `True`, only accept events where `wiki == "enwiki"`. |
| `top_headlines` | `int` | `10` | Maximum *distinct* headlines printed per window. |
| `max_words` | `int` | `8` | Hard cap on generated headline token length. |
| `jaccard_threshold` | `float` | `0.55` | Token *Jaccard similarity* threshold for clustering (lower ⇒ more merging). |
| `phrasal_fuse_threshold` | `float` | `0.88` | difflib ratio for fusing near-duplicate phrasings. |
| `min_edits_for_llm` | `int` | `12` | Minimum edits in window before calling LLM (fallback otherwise). |
| `ollama_host` | `str` | `"http://localhost:11434"` | Ollama base URL. |
| `ollama_model` | `str` | `"llama3.2:1b"` | Model name visible in `ollama list`. |
| `temperature` | `float` | `0.7` | Generation temperature for LLM calls. |
| `seed` | `int` | `42` | Random seed for reproducibility. |
| `num_ctx` | `int` | `512` | Context tokens (CPU-safe). |
| `num_gpu` | `int` | `0` | `0` forces CPU. |
| `request_timeout_s` | `int` | `60` | HTTP timeout for LLM requests. |
| `sse_retry_base_s` | `int` | `3` | Linear backoff step on SSE errors. |
| `sse_retry_max_s` | `int` | `90` | Max backoff cap for SSE reconnects. |

### Constants

| Name | Type | Description |
|---|---|---|
| `STOPWORDS` | `set[str]` | Generic content/admin words to remove from scoring/tokens (e.g., "article", "references"). |
| `ADMIN_TERMS` | `set[str]` | Admin/maintenance vocabulary to de-emphasize (e.g., "talk", "rfd", "template"). |

---

## `app/stream.py` - connects to Wikimedia SSE and batch events 

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `_size_delta` | `(change: Dict) -> int` | `int` | Safely extract absolute byte delta from `recentchange` event (`length.old/new` or `revision.old/new.size`). |
| `event_generator` | `(s: Settings) -> Generator[Dict, None, None]` | generator of dicts | Persistent SSE reader with linear backoff + jitter. Yields normalized events: `{title, comment, user, ts, delta}`; filters to enwiki if configured. Skips non-dict heartbeats. |
| `collect_window` | `(gen: Generator[Dict, None, None], seconds: int) -> list[Dict]` | `list[dict]` | Pulls from `event_generator` for `seconds`, returning a list of normalized events for this batch. |

### Event Shape (yielded from `event_generator`)
| Key | Type | Description |
|---|---|---|
| `title` | `str` | Normalized title (ASCII words only) from `cleaning.normalize_title`. |
| `comment` | `str` | Normalized comment (ASCII words only) from `cleaning.normalize_comment`. |
| `user` | `str` | Raw username from event. |
| `ts` | `int` | Event timestamp (epoch). |
| `delta` | `int` | Absolute byte change for the edit. |

---

## `app/cleaning.py` - normalise text and tokenise for clustering

### Constants

| Name | Type | Description |
|---|---|---|
| `NS_PREFIXES` | `set[str]` | Leading namespaces to strip from titles (e.g., `"talk"`, `"category"`, `"draft"`). |
| `EXCLUDE_TOKENS` | `set[str]` | Always-ignored tokens for analysis (e.g., `"whatlinkshere"`, `"category"`, `"wp"`). |
| `RE_LINKS` | `re.Pattern` | Matches wiki link/templating markers `[[ ]]`, `{{ }}`. |
| `RE_URL` | `re.Pattern` | Matches `http(s)://` URLs. |
| `RE_NONLET` | `re.Pattern` | Matches non-ASCII letters (used to drop diacritics for analysis tokens). |
| `RE_SPACES` | `re.Pattern` | Collapses runs of whitespace. |
| `RE_NS` | `re.Pattern` | Captures a leading `Namespace:Title` split. |

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `normalize_title` | `(title: str) -> str` | `str` | Strip namespace, slashes, links/URLs; return ASCII-only words; drop `EXCLUDE_TOKENS`. For analysis/clustering. |
| `normalize_comment` | `(comment: str) -> str` | `str` | Remove `[[..]]`, URLs; return ASCII-only words; drop `EXCLUDE_TOKENS`. For analysis/scoring. |
| `strip_admin_markup` | `(text: str) -> str` | `str` | Remove links/URLs; collapse spaces; **keeps diacritics** for display/LLM context. |
| `words_for_similarity` | `(text: str) -> set[str]` | `set[str]` | Build token set (unigrams + bigrams, length ≥4) minus `STOPWORDS`/`ADMIN_TERMS`. Feeds Jaccard clustering. |

---

## `app/llm.py` - builds prompts, handles Ollama, and cleans headline outputs

### Constants

| Name | Type | Description |
|---|---|---|
| `BAN_WORDS` | `set[str]` | Words disallowed in final headlines (e.g., `"whatlinkshere"`, `"wikiproject"`, `"category"`). |

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `batch_context` | `(entries: list[dict], max_chars: int = 600) -> str` | `str` | Compose compact context: common terms + short example lines (diacritics preserved). |
| `_strip_bad_punct_keep_apostrophe` | `(s: str) -> str` | `str` | Strip links/angle/quote junk; keep letters, spaces, apostrophes, hyphens; collapse spaces. |
| `clean_headline` | `(h: str, max_words: int) -> str` | `str` | NFC normalize; drop `BAN_WORDS`; limit to `max_words`; basic title-case; return empty if too short. |
| `_parse_json_array` | `(text: str) -> list[str]` | `list[str]` | Parse model output as array or object→array; fallback to `[...]` substring if present. |
| `_call_ollama` | `(prompt: str, s: Settings, temperature: float) -> str` | `str` | Single Ollama call with `format: "json"`; returns raw `response` string. |
| `generate_batch_headlines` | `(entries: list[dict], mood: str, s: Settings, n: int) -> list[str]` | `list[str]` | Two-pass strict JSON generation (cooler retry), sanitize + dedupe, cap to `n`; fallback to extractive headlines on failure. |

---

## `app/scoring.py` - scores by bytes/frequency and merges near-duplicates

### Constants / Regex

| Name | Type | Description |
|---|---|---|
| `RE_WORDS3` | `re.Pattern` | ASCII word extractor (`[a-zA-Z]{3,}`) for term maps/scoring. |

### Helper Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `_norm_for_fuzzy` | `(s: str) -> str` | `str` | Strip accents; keep ASCII letters/digits/apostrophes/spaces; lowercased—used for phrasal fuzzy matching. |
| `_tokens` | `(text: str) -> Iterator[str]` | generator | Yield ASCII tokens (len ≥3) minus `STOPWORDS`/`ADMIN_TERMS`. |

### Term Maps & Scoring

| Name | Signature | Returns | Description |
|---|---|---|---|
| `term_maps` | `(entries: list[dict]) -> tuple[Counter, Counter]` | `(term_bytes, term_counts)` | Build both byte and frequency maps for the current window (`delta`-weighted + raw counts). |
| `_unit_scale` | `(term_bytes: Counter, term_counts: Counter) -> int` | `int` | Average bytes per token occurrence (≥1) for frequency scaling. |
| `score_headline_blend` | `(headline: str, term_bytes: Counter, term_counts: Counter, blend: float = 0.80) -> int` | `int` | `score = blend*bytes + (1-blend)*freq*unit_scale` (prevents walls of zeros). |

### Clustering & Diversity

| Name | Signature | Returns | Description |
|---|---|---|---|
| `jaccard_tokens` | `(a: str, b: str) -> float` | `float` | Jaccard similarity of `words_for_similarity` token sets. |
| `cluster_and_merge` | `(scored: list[tuple[str,int]], sim_thresh: float = 0.55)` | `list[tuple[str,int,list]]` | Merge by token Jaccard; sum scores; keep best-scoring representative. Returns `[(repr, total_score, members)]`. |
| `fuse_phrasal_near_dupes` | `(clusters: list[tuple[str,int,list]], threshold: float = 0.88)` | `list[tuple[str,int,list]]` | Fuse clusters whose **representatives** are paraphrases (difflib ratio). Sums scores & members. |
| `mmr_select` | `(candidates: list[tuple[str,int]], k: int = 10, sim_fn=jaccard_tokens, lambda_div: float = 0.75)` | `list[tuple[str,int]]` | (Optional) Maximal Marginal Relevance: trade-off relevance vs. redundancy. Not used by default. |

### Legacy / Simple

| Name | Signature | Returns | Description |
|---|---|---|---|
| `byte_term_map` | `(entries: list[dict]) -> Counter` | `Counter` | Byte-only term map (legacy; term_maps is preferred). |
| `score_headline` | `(headline: str, term_bytes: Counter) -> int` | `int` | Sum of bytes for headline tokens (legacy). |

### Fallback

| Name | Signature | Returns | Description |
|---|---|---|---|
| `simple_fallback_headlines` | `(entries: list[dict], n: int, max_words: int) -> list[str]` | `list[str]` | Deterministic extractive headlines if LLM fails. (Imported/used by `llm.generate_batch_headlines`.) |

---

## `app/main.py` - handles the rolling input stream loop and prints top headlines

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `run` | `(settings: Settings) -> None` | `None` | Orchestrates rolling windows: collect → mood → LLM candidates → blended scoring → cluster + fuse → print top K `(headline, score)`. |
| `__main__` | — | — | CLI entrypoint; parses flags (`--seconds`, `--headlines`, `--max-words`, `--jaccard`), constructs `Settings`, then calls `run`. |

### CLI Flags

| Flag | Type | Description |
|---|---|---|
| `--seconds` | `int` | Window length; overrides `Settings.batch_seconds`. |
| `--headlines` | `int` | Max distinct headlines; overrides `Settings.top_headlines`. |
| `--max-words` | `int` | Headline word cap; overrides `Settings.max_words`. |
| `--jaccard` | `float` | Clustering threshold; overrides `Settings.jaccard_threshold`. |

---

## Data Shapes (for reference)

### Input event (raw, from SSE)
```json
{
  "type": "edit",
  "wiki": "enwiki",
  "title": "Some page",
  "comment": "Edit summary",
  "length": {"old": 1234, "new": 1288},
  "revision": {"old": {"size": 1234}, "new": {"size": 1288}},
  "timestamp": 1730554000,
  "user": "Someone"
}
```

### Normalised entry (pipeline)
```json
{
  "title": "Some page",       // ASCII words only
  "comment": "Edit summary",  // ASCII words only
  "user": "Someone",
  "ts": 1730554000,
  "delta": 54                 // absolute byte difference
}
```
