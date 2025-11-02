"""
Minimal API layer that exposes your live Wikipedia edit headlines.

Endpoints
---------
GET  /health        -> {"status":"ok"}
GET  /config        -> current runtime settings (subset)
GET  /recent?n=100  -> most-recent N records as JSON (default 100)
GET  /stream        -> text/event-stream (SSE, NDJSON in "data:" lines)

How it works
------------
- A background producer consumes `event_generator(Settings)` (your existing
  stream backend), generates a headline (LLM + fallback), computes VADER
  sentiment, then broadcasts one JSON record per edit.
- Each connected client gets a dedicated asyncio.Queue and receives the records
  in real time via SSE.
- A bounded deque keeps the last 1,000 records for /recent snapshots.

Run
---
uvicorn app.api:app --host 0.0.0.0 --port 8000 --reload

Consume (TypeScript)
--------------------
SSE:
  const evt = new EventSource("http://localhost:8000/stream");
  evt.onmessage = (e) => { const obj = JSON.parse(e.data); ... };

Polling:
  const res = await fetch("http://localhost:8000/recent?n=200");
  const items = await res.json();
"""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, List, Set

import nltk
from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, StreamingResponse
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import Settings
from stream import event_generator
from llm import generate_headline_for_edit

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# -----------------------------------------------------------------------------
# Globals
# -----------------------------------------------------------------------------
settings = Settings()

# recent ring buffer (for /recent snapshots)
RECENT_MAX = 1000
_recent: Deque[Dict] = deque(maxlen=RECENT_MAX)

# connected clients (each is an asyncio.Queue of dicts)
_clients: Set[asyncio.Queue] = set()

# sentiment analyzer on headlines
nltk.download("vader_lexicon", quiet=True)
_vader = SentimentIntensityAnalyzer()

# lifecycle control
_stop_event = asyncio.Event()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _sentiment(compound: float) -> str:
    return "positive" if compound > 0.2 else "negative" if compound < -0.2 else "neutral"


def _record_from_event(ev: Dict) -> Dict:
    """Build the final JSON record you already use in main.py."""
    title = ev.get("title", "")
    comment = ev.get("comment", "") or "No comment"
    editor = ev.get("user", "")
    delta = int(ev.get("delta", 0))
    is_edit = bool(ev.get("is_edit", False))
    is_bot = bool(ev.get("is_bot", False))
    ts = int(ev.get("timestamp", 0))

    # Generate headline (robust: LLM + extractive fallback inside your llm.py)
    headline = generate_headline_for_edit(title, comment, settings)

    # Sentiment on the generated headline
    comp = _vader.polarity_scores(headline)["compound"]

    return {
        "headline": headline,
        "title": title,
        "editor": editor,
        "byte_diff": delta,
        "comment": comment,
        "sentiment": {"label": _sentiment(comp), "compound": round(comp, 3)},
        # "is_edit": is_edit,
        # "is_bot": is_bot,
        # "wiki": ev.get("wiki", "enwiki"),
        # "namespace": ev.get("namespace", 0),
        # "timestamp": ts,
        "iso_time": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
    }


async def _broadcast(obj: Dict) -> None:
    """Put the object into every subscriber's queue (non-blocking)."""
    if not _clients:
        return
    for q in list(_clients):
        try:
            q.put_nowait(obj)
        except asyncio.QueueFull:
            # Slow client: drop message to avoid backpressure
            pass


async def _producer_loop() -> None:
    """Background task: read stream -> build record -> save + broadcast."""
    try:
        gen = event_generator(settings)
        for ev in gen:
            if _stop_event.is_set():
                break
            rec = _record_from_event(ev)
            _recent.append(rec)
            await _broadcast(rec)
    except Exception as e:
        log.exception("Producer crashed: %s", e)


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title="HTB Headlines API", version="1.0.0")

# CORS for local dev / TS frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    log.info("Starting producer loop…")
    # run the blocking generator inside a thread so it doesn't block the loop
    asyncio.create_task(asyncio.to_thread(asyncio.run, _producer_loop()))


@app.on_event("shutdown")
async def _shutdown():
    log.info("Shutting down…")
    _stop_event.set()


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/config")
async def get_config():
    # Return a small, TS-friendly snapshot (avoid leaking secrets if you add any)
    return {
        "batch_mode": "per-edit",
        "model": settings.ollama_model,
        "host": settings.ollama_host,
        "max_words": settings.max_words if hasattr(settings, "max_words") else 8,
        "filters": {
            "enwiki_only": settings.enwiki_only,
            "namespace": 0,
            "type": "edit",
            "min_byte_abs": getattr(settings, "min_abs_bytes", 0),
            "no_bots": True,
            "require_title": True,
            "require_comment": False,
        },
    }


@app.get("/recent")
async def recent(n: int = 100):
    """Return the N most recent records (default 100, max 1000)."""
    n = max(1, min(n, RECENT_MAX))
    items = list(_recent)[-n:]
    return JSONResponse(items)


@app.get("/stream")
async def stream(request: Request):
    """
    SSE: 'text/event-stream' that sends one JSON object per message.

    TS consumption:
      const es = new EventSource("http://localhost:8000/stream");
      es.onmessage = (e) => { const obj = JSON.parse(e.data); ... };
    """
    # one queue per client
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _clients.add(q)

    async def event_gen():
        try:
            # Optional: send a hello comment line (not a data event)
            yield b": connected\n\n"
            while True:
                # client disconnected?
                if await request.is_disconnected():
                    break
                obj = await q.get()
                data = json.dumps(obj, ensure_ascii=False)
                # SSE frame: "data: {json}\n\n"
                yield f"data: {data}\n\n".encode("utf-8")
        except asyncio.CancelledError:
            pass
        finally:
            _clients.discard(q)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # for nginx
    }
    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=headers)
