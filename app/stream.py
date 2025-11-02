# app/stream.py
"""
Event streaming utilities:
- event_generator(): persistent SSE reader with retry/backoff + normalization
- collect_window(): time-boxed collector for rolling windows
"""

import json
import time
import random
import logging
from typing import Dict, Generator, List
from requests_sse import EventSource

from config import Settings
from cleaning import normalize_title, normalize_comment

log = logging.getLogger(__name__)


def _size_delta(change: Dict) -> int:
    """Best-effort absolute byte delta from a recentchange event."""
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


def event_generator(s: Settings) -> Generator[Dict, None, None]:
    """
    Yield normalized change dicts from a persistent SSE connection.
    Auto-reconnects with exponential backoff + jitter on errors.
    """
    headers = {"User-Agent": "HTB-Headlines/1.0", "Accept": "text/event-stream"}
    backoff = s.sse_retry_base_s  # e.g., 3s
    while True:
        try:
            with EventSource(s.stream_url, headers=headers) as stream:
                for event in stream:
                    if event.type != "message" or not event.data:
                        continue
                    try:
                        raw = json.loads(event.data)
                        if not isinstance(raw, dict):
                            continue                    # ← ignore non-dict payloads
                    except json.JSONDecodeError:
                        continue
                    if s.enwiki_only and raw.get("wiki") != "enwiki":
                        continue
                    yield {
                        "title":   normalize_title(raw.get("title", "")),
                        "comment": normalize_comment(raw.get("comment", "")),
                        "user":    raw.get("user", ""),
                        "ts":      raw.get("timestamp", 0),
                        "delta":   _size_delta(raw),
                    }
        except Exception as e:
            wait = min(backoff, s.sse_retry_max_s) + (random.random() * 0.5)
            log.warning("stream error: %s; retrying in %.1fs", e, wait)
            time.sleep(wait)
            backoff = min(backoff + s.sse_retry_base_s, s.sse_retry_max_s)   # ← linear + cap
        else:
            backoff = s.sse_retry_base_s   # ← reset after a clean session


def collect_window(gen: Generator[Dict, None, None], seconds: int) -> List[Dict]:
    """
    Collect events from `gen` for approximately `seconds`.
    (Blocks on next() until an event arrives or the window elapses.)
    """
    out, start = [], time.time()
    while time.time() - start < seconds:
        try:
            out.append(next(gen))
        except StopIteration:
            break
        except Exception as e:
            # transient generator errors shouldn't kill the window
            log.debug("collect_window: %s", e)
            break
    return out
