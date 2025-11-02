# app/stream.py
"""
SSE stream reader for Wikimedia RecentChanges with strict backend filters.

Yields only events that pass ALL of these gates:
  1) English Wikipedia only (wiki == "enwiki")            [config: enwiki_only]
  2) Article namespace only (namespace/ns == 0)           [config: allowed_namespaces]
  3) Edit events only (type == "edit")
  4) Not a bot (bot != True)
  5) Has a non-trivial title (length >= min_title_len)
  6) Has a non-empty trimmed comment (require_comment = True)
  7) Absolute byte delta >= min_byte_diff

Emitted dict per qualifying event:
  {
    "title":   <cleaned title>,
    "comment": <cleaned comment>,
    "user":    <editor>,
    "ts":      <unix timestamp>,
    "delta":   <abs byte diff>,
    "is_edit": True,
    "is_bot":  False
  }
"""

import json
import time
import random
import logging
from typing import Dict, Generator
from requests_sse import EventSource

from config import Settings
from cleaning import normalize_title, normalize_comment

log = logging.getLogger(__name__)


def _size_delta(change: Dict) -> int:
    """Compute absolute byte delta from multiple possible RC schemas."""
    # Primary schema
    length = change.get("length") or {}
    old = length.get("old")
    new = length.get("new")
    if isinstance(old, int) and isinstance(new, int):
        return abs(new - old)

    # Fallback (older RC formats)
    rev = change.get("revision") or {}
    osz = (rev.get("old") or {}).get("size")
    nsz = (rev.get("new") or {}).get("size")
    if isinstance(osz, int) and isinstance(nsz, int):
        return abs(nsz - osz)

    return 0


def event_generator(s: Settings) -> Generator[Dict, None, None]:
    """
    Persistent SSE generator with bounded, jittered backoff on errors.
    Applies backend filters before yielding.
    """
    headers = {"User-Agent": "HTB-Headlines/1.0", "Accept": "text/event-stream"}

    # ---- Filter knobs (safe defaults if not present in Settings)
    enwiki_only       = getattr(s, "enwiki_only", True)
    allowed_namespaces = set(getattr(s, "allowed_namespaces", {0}))  # main/article ns=0
    require_comment   = getattr(s, "require_comment", True)
    min_title_len     = int(getattr(s, "min_title_len", 4))
    min_byte_diff     = int(getattr(s, "min_byte_diff", 20))

    backoff = 2  # seconds (will be jittered and capped at 30)

    while True:
        try:
            with EventSource(s.stream_url, headers=headers) as stream:
                for event in stream:
                    if event.type != "message" or not event.data:
                        continue

                    # Parse JSON safely; ignore non-dict payloads (e.g., heartbeats)
                    try:
                        raw = json.loads(event.data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict):
                        continue

                    # ---- Hard gates
                    if enwiki_only and raw.get("wiki") != "enwiki":
                        continue

                    # Namespace can be "namespace" or "ns" depending on RC variant
                    ns = raw.get("namespace")
                    if ns is None:
                        ns = raw.get("ns")
                    # Ensure namespace is an int for comparison
                    try:
                        ns = int(ns)
                    except (TypeError, ValueError):
                        continue
                    if ns not in allowed_namespaces:
                        continue

                    # Edits only
                    typ = str(raw.get("type") or "")
                    if typ != "edit":
                        continue

                    # Not a bot
                    if raw.get("bot") is True:
                        continue

                    # Title / comment presence
                    title_raw   = str(raw.get("title", "") or "")
                    comment_raw = str(raw.get("comment", "") or "")
                    if len(title_raw) < min_title_len:
                        continue
                    if require_comment and len(comment_raw.strip()) == 0:
                        continue

                    # Byte delta gate
                    delta = _size_delta(raw)
                    if delta < min_byte_diff:
                        continue

                    # ---- Normalize AFTER gating
                    yield {
                        "title":   normalize_title(title_raw),
                        "comment": normalize_comment(comment_raw),
                        "user":    raw.get("user", ""),
                        "ts":      int(raw.get("timestamp", 0) or 0),
                        "delta":   delta,
                        "is_edit": True,
                        "is_bot":  False,
                    }

        except Exception as e:
            wait = min(backoff, 30) + random.uniform(0.25, 0.75)
            log.warning("stream error: %s; retrying in %.1fs", e, wait)
            time.sleep(wait)
            backoff = min(backoff * 2, 30)  # exponential backoff, capped
        else:
            backoff = 2  # reset after clean loop


def collect_window(gen: Generator[Dict, None, None], seconds: int):
    """(Legacy helper) Collect events for `seconds` from a persistent generator."""
    out, start = [], time.time()
    while time.time() - start < seconds:
        try:
            out.append(next(gen))
        except StopIteration:
            break
    return out
