# app/main.py
import json
import logging
import nltk
from datetime import datetime, timezone
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from config import Settings
from stream import event_generator
from llm import generate_headline_for_edit

log = logging.getLogger(__name__)

def _sentiment_label(compound: float) -> str:
    """Map VADER compound score to a coarse label."""
    return "positive" if compound > 0.2 else "negative" if compound < -0.2 else "neutral"

def run(settings: Settings):
    """Continuously read the live stream and print one JSON object per qualifying edit."""
    # Sentiment for the *generated headline*
    nltk.download("vader_lexicon", quiet=True)
    vader = SentimentIntensityAnalyzer()

    gen = event_generator(settings)
    print("🔴 Live stream started. Press Ctrl+C to stop.")

    for ev in gen:
        # ev is guaranteed filtered + normalized by stream.py
        title   = ev.get("title", "")
        comment = ev.get("comment", "")
        editor  = ev.get("user", "")
        delta   = int(ev.get("delta", 0))
        is_edit = bool(ev.get("is_edit", False))
        is_bot  = bool(ev.get("is_bot", False))
        ts      = int(ev.get("timestamp", 0))

        # Headline (robust call with fallback already handled inside)
        headline = generate_headline_for_edit(title, comment, settings)

        # Sentiment on the *headline*
        comp = vader.polarity_scores(headline)["compound"]
        sentiment = {
            "label": _sentiment_label(comp),
            "compound": round(comp, 3)
        }

        # Emit one compact JSON line (UTF-8, no ASCII escaping)
        record = {
            "headline": headline,                  # Headline Generated
            "title": title,                        # Wikipedia Title (normalized)
            "editor": editor,                      # Editor (username/IP)
            "byte_diff": delta,                    # +/- bytes for this edit
            "comment": comment or "No comment",    # Edit summary (cleaned)
            "sentiment": sentiment,                # VADER result on the headline
            # "is_edit": is_edit,                    # Must be true for qualifying events
            # "is_bot": is_bot,                      # Whether editor is flagged bot
            # "wiki": ev.get("wiki", "enwiki"),
            # "namespace": ev.get("namespace", 0),
            # "timestamp": ts,
            "iso_time": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        }

        print(json.dumps(record, ensure_ascii=False))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(Settings())
