# bbm-htb-2025 - "WikiWatch: The Climate of Wikipedia"

**WikiWatch** is a real-time pipeline and application *that projects the climate of Wikipedia.* It converts Wikimedia’s RecentChanges stream of page edits into concise, newsroom-style headlines using a local Llama model (via Ollama). It ingests live edits, normalises text inputs, filters information, and shows these headlines. Through VADER-based sentiment analysis, the program also classifies these headlines into one of Positive, Negative or Neutral based on perceived mood. All of these are displayed through a fun and colourful user interface inspired by [Listen to Wikipedia](http://listen.hatnote.com/).

<br>

## Developers
- aragamisonatina
- beppermon
- GregJHH
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
- TypeScript [insert version here]
- Python 3.11 (basis for backend)
- Llama 3.2:1b (generation)
- ChatGPT / Github CoPilot (logic and coding guidance)

<br>

# Python API Reference / Cheatsheet

This document lists **every public constant, function, and class** in the `app/` codebase with concise descriptions, reflecting the **per-edit streaming** architecture (one JSON line per qualifying edit).

**NOTE:** All implementations in Python have been moved to TypeScript due to local compatibility issues. However, this implementation is a work of concept that still functions and can be used for your own projects.

---

## `app/config.py` — global settings & shared word lists  :contentReference[oaicite:0]{index=0}

### Class: `Settings` (frozen dataclass)

| Field | Type | Default | Description |
|---|---|---:|---|
| `stream_url` | `str` | `"https://stream.wikimedia.org/v2/stream/mediawiki.recentchange"` | Wikimedia RecentChanges SSE endpoint. |
| `enwiki_only` | `bool` | `True` | If `True`, only accept events where `wiki == "enwiki"`. |
| `max_words` | `int` | `8` | Hard cap on generated headline token length (per-edit). |
| `print_errors` | `bool` | `True` | Log LLM failures inline while streaming. |
| `min_bytes_for_llm` | `int` | `0` | If `> 0`, only call LLM when `byte_diff >= value`. |
| `ollama_host` | `str` | `"http://localhost:11434"` | Ollama base URL. |
| `ollama_model` | `str` | `"llama3.2:1b"` | Model name visible in `ollama list`. |
| `temperature` | `float` | `0.6` | Slightly cool for single-edit stability. |
| `seed` | `int` | `42` | Random seed for determinism. |
| `num_ctx` | `int` | `256` | Small context (per-edit). |
| `num_gpu` | `int` | `0` | `0` forces CPU. |
| `request_timeout_s` | `int` | `30` | HTTP timeout for LLM calls. |
| `sse_retry_base_s` | `int` | `3` | Base backoff seconds on SSE errors. |
| `sse_retry_max_s` | `int` | `20` | Max backoff for SSE reconnects. |
| `allowed_namespaces` | `tuple` | `(0,)` | Allowed namespaces (default: article/Main). |
| `require_comment` | `bool` | `True` | Require non-empty edit comment. |
| `min_title_len` | `int` | `4` | Minimum raw title length before normalization. |
| `min_byte_diff` | `int` | `20` | Minimum absolute byte delta for inclusion. |

### Constants

| Name | Type | Description |
|---|---|---|
| `STOPWORDS` | `set[str]` | Generic/admin words removed from analysis (e.g., “article”, “references”). |
| `ADMIN_TERMS` | `set[str]` | Admin/maintenance vocabulary to de-emphasize (e.g., “talk”, “rfd”, “template”). |

---

## `app/stream.py` — connect to Wikimedia SSE, filter, and yield events  :contentReference[oaicite:1]{index=1}

**Backend filters (all must pass):** enwiki only; namespace ∈ `allowed_namespaces` (default `{0}`); `type == "edit"`; `bot != True`; `len(title) >= min_title_len`; (if `require_comment`) non-empty comment; `abs(byte_diff) >= min_byte_diff`.

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `event_generator` | `(s: Settings) -> Generator[Dict, None, None]` | generator of dicts | Persistent SSE reader with bounded, jittered backoff. Applies **all filters** and yields normalized events (see “Event Shape”). |
| `collect_window` | `(gen: Generator[Dict, None, None], seconds: int)` | `list[dict]` | Legacy helper: collect events for a fixed number of seconds. |

> Internal helper: `_size_delta(change: Dict) -> int` computes absolute byte delta from `length.old/new` or `revision.old/new.size`.

### Event Shape (yielded per qualifying edit)

| Key | Type | Description |
|---|---|---|
| `title` | `str` | Cleaned title (words only; namespaces removed). |
| `comment` | `str` | Cleaned edit summary (links/URLs removed). |
| `user` | `str` | Editor name or IP. |
| `ts` | `int` | Unix timestamp. |
| `delta` | `int` | Absolute byte difference for the edit. |
| `is_edit` | `bool` | Always `True` for yielded events. |
| `is_bot` | `bool` | Always `False` (bot edits are filtered out). |

---

## `app/cleaning.py` — normalize text & provide similarity tokens  :contentReference[oaicite:2]{index=2}

### Constants

| Name | Type | Description |
|---|---|---|
| `NS_PREFIXES` | `set[str]` | Leading namespaces to strip from titles (e.g., `"talk"`, `"category"`, `"draft"`). |
| `EXCLUDE_TOKENS` | `set[str]` | Tokens always dropped from analysis (e.g., `"whatlinkshere"`, `"category"`, `"wp"`). |
| `RE_LINKS` | `re.Pattern` | Matches wiki link/templating markers `[[ ]]`, `{{ }}`. |
| `RE_URL` | `re.Pattern` | Matches `http(s)://…` URLs. |
| `RE_SPACES` | `re.Pattern` | Collapses runs of whitespace. |
| `RE_NS` | `re.Pattern` | Captures leading `Namespace:Title` split. |
| `RE_NONLET_ASCII` | `re.Pattern` | Strips non-ASCII letters for ASCII-only tokenization. |

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `normalize_title` | `(title: str) -> str` | `str` | Strip namespace, slashes, markup/URLs; ASCII words only; drop `EXCLUDE_TOKENS`. |
| `normalize_comment` | `(comment: str) -> str` | `str` | Remove `[[…]]`, URLs; ASCII words only; drop `EXCLUDE_TOKENS`. |
| `strip_admin_markup` | `(text: str) -> str` | `str` | Remove links/URLs and collapse spaces (diacritics preserved). |

---

## `app/llm.py` — build per-edit headline prompt & sanitize output  :contentReference[oaicite:3]{index=3}

### Constants

| Name | Type | Description |
|---|---|---|
| `BAD_SINGLETONS` | `set[str]` | Disallowed trivial outputs (e.g., `"true"`, `"ok"`, `"headline"`). |

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `generate_headline_for_edit` | `(title: str, comment: str, s: Settings) -> str` | `str` | Calls Ollama **once per edit** with a strict system/user prompt (no JSON). Cleans the model text, validates it with heuristics, and falls back to an extractive title if needed. |
| `looks_like_headline` | `(text: str, max_words: int = 12, min_words: int = 2) -> bool` | `bool` | Heuristics to reject junk (singleton booleans, too short/long, low letter density). |

> Internal helpers: `_clean_text_keep_apostrophes(s)`, `_extractive_fallback(title, comment, max_words)`.

---

## `app/main.py` — per-edit loop: generate headline, sentiment-tag, emit JSON  :contentReference[oaicite:4]{index=4}

### Functions

| Name | Signature | Returns | Description |
|---|---|---|---|
| `run` | `(settings: Settings) -> None` | `None` | Starts the live stream, and for **each qualifying edit**: generates a headline with `llm.generate_headline_for_edit`, scores sentiment (VADER), and prints **one JSON record**. |

> Internal helper: `_sentiment_label(compound: float) -> str` maps VADER compound to `positive`/`neutral`/`negative`.

### Output JSON (one line per edit)

```json
{
  "headline": "Clean human headline",
  "title": "Normalized title",
  "editor": "UsernameOrIP",
  "byte_diff": 42,
  "comment": "Normalized edit summary",
  "sentiment": { "label": "neutral", "compound": 0.0 },
  "iso_time": "2025-11-02T20:15:30+00:00"
}
```
