import pandas as pd
import nltk
import random
import re
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from collections import Counter, defaultdict

# Download sentiment lexicon (only once)
nltk.download('vader_lexicon')

# === Load CSV ===
df = pd.read_csv("htb_sample_dataset.csv", encoding="latin1")

# === Initialize sentiment analyzer ===
analyzer = SentimentIntensityAnalyzer()

# === Data collection ===
entries = []
all_keywords = []

for _, row in df.iterrows():
    title = str(row['Title'])
    edit = str(row['Edit'])
    full_text = f"{title.strip()}: {edit.strip()}"

    # Sentiment score
    sentiment = analyzer.polarity_scores(edit)['compound']

    # Extract "important" words (length ≥ 5 to avoid fillers)
    keywords = re.findall(r'\b[a-zA-Z]{5,}\b', full_text.lower())
    all_keywords.extend(keywords)

    entries.append({
        'text': full_text,
        'sentiment': sentiment,
        'keywords': keywords
    })

# === Overall mood ===
avg_sentiment = sum(e['sentiment'] for e in entries) / len(entries)
general_mood = "positive" if avg_sentiment > 0.2 else "negative" if avg_sentiment < -0.2 else "neutral"
print(f"\n🧠 Wikipedia's current mood: {general_mood.upper()}")

# === Identify hot topics ===
keyword_counts = Counter(all_keywords)
top_keywords = [kw for kw, _ in keyword_counts.most_common(8)]  # adjust # if needed

# === Group edits by keyword topics ===
topic_clusters = defaultdict(list)
for entry in entries:
    matched = False
    for kw in entry['keywords']:
        if kw in top_keywords:
            topic_clusters[kw].append(entry)
            matched = True
    if not matched:
        topic_clusters['misc'].append(entry)

# === Generate Headline-like Insights ===
print("\n📰 WIKIPEDIA'S HEADLINES:")

headline_templates = [
    "Rising attention on '{}' after multiple article updates.",
    "Wikipedia sees a spike in edits related to '{}'.",
    "Several pages edited around '{}', marking it a trending topic.",
    "Topic '{}' gains momentum in recent Wikipedia activity.",
    "In focus: '{}' — newly revised and heavily edited."
]

for topic, items in topic_clusters.items():
    if len(items) < 2:
        continue

    template = random.choice(headline_templates)
    headline = template.format(topic.capitalize())
    print("→", headline)
