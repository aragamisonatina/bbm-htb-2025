import pandas as pd
import nltk
import random
import re
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from collections import Counter, defaultdict

import json
from requests_sse import EventSource
import pandas as pd
import time

# URL for the Wikimedia recent changes stream
url = 'https://stream.wikimedia.org/v2/stream/mediawiki.recentchange'

# Create a list to store edits
edits = []

# Dataframe updated as events arrive
df = pd.DataFrame(columns=['user', 'title', 'comment', "timestamp"])

# Adding headers can help in case the server requires specific request formatting
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.83 Safari/537.36'
}


# Function to determine if the change is to a talk page
def is_talk_page(title):
    # Typically, talk pages start with "Talk:" or "<Language> talk:"
    # This will handle "Talk:", "User talk:", "Wikipedia talk:", etc.
    return any(title.lower().startswith(prefix) for prefix in ['talk:', 'wikipedia talk:', 'file talk:',
                                                               'template talk:', 'help talk:', 'category talk:',
                                                               'portal talk:',
                                                               'book talk:', 'draft talk:', 'timedtext talk:',
                                                               'module talk:'])


# Setting up the EventSource connection
with EventSource(url, headers=headers) as stream:
    for event in stream:

        if event.type == 'message':
            try:
                # Parse the event data as JSON
                change = json.loads(event.data)
                # Filter for human talk page edits on english wikipedia
                if is_talk_page(change['title']) and change['bot'] == False and change["wiki"] == "enwiki":
                    edit = {
                        "user": change["user"],
                        "title": change["title"],
                        "comment": change["comment"],
                        "timestamp": change["timestamp"]
                    }
                    edits.append(edit)
                    # Update dataframe immediately
                    df.loc[len(df)] = [edit["user"], edit["title"], edit["comment"], edit["timestamp"]]
                    print(f'{edit["user"]} edited {edit["title"]} with comment: {edit["comment"]}')
                    # Save it to df every 100 edits
                    if len(df) % 30 == 0:
                        df.to_csv("english_talk_edits.csv", index=False)
            except ValueError:
                # In case of any issues in parsing JSON data
                continue

# DataFrame has been updated incrementally during the stream


### MY CODE STARTS HERE


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
