import pandas as pd
import nltk
import random
import re
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from collections import Counter, defaultdict
import json

# Download sentiment lexicon (only once)
try:
    nltk.download('vader_lexicon', quiet=True)
except:
    pass

class WikiNewsGenerator:
    def __init__(self, csv_file="htb_sample_dataset.csv"):
        self.df = pd.read_csv(csv_file, encoding="latin1")
        self.analyzer = SentimentIntensityAnalyzer()
        self.entries = []
        self.all_keywords = []
        
    def analyze_edits(self):
        """Analyze all edits from the CSV"""
        for _, row in self.df.iterrows():
            title = str(row['Title'])
            edit = str(row['Edit'])
            full_text = f"{title.strip()}: {edit.strip()}"

            # Sentiment score
            sentiment = self.analyzer.polarity_scores(edit)['compound']

            # Extract "important" words (length ≥ 5 to avoid fillers)
            keywords = re.findall(r'\b[a-zA-Z]{5,}\b', full_text.lower())
            self.all_keywords.extend(keywords)

            self.entries.append({
                'title': title,
                'edit': edit,
                'text': full_text,
                'sentiment': sentiment,
                'keywords': keywords
            })
        
        return self.entries
    
    def get_overall_mood(self):
        """Calculate overall Wikipedia mood"""
        avg_sentiment = sum(e['sentiment'] for e in self.entries) / len(self.entries)
        if avg_sentiment > 0.2:
            return "positive", avg_sentiment
        elif avg_sentiment < -0.2:
            return "negative", avg_sentiment
        else:
            return "neutral", avg_sentiment
    
    def generate_headlines(self, num_headlines=5):
        """Generate headline predictions based on edit patterns"""
        # Identify hot topics
        keyword_counts = Counter(self.all_keywords)
        top_keywords = [kw for kw, _ in keyword_counts.most_common(15)]
        
        # Group edits by keyword topics
        topic_clusters = defaultdict(list)
        for entry in self.entries:
            matched = False
            for kw in entry['keywords']:
                if kw in top_keywords:
                    topic_clusters[kw].append(entry)
                    matched = True
                    break
            if not matched:
                topic_clusters['general'].append(entry)
        
        # Generate headlines
        headlines = []
        headline_templates = [
            "Breaking: {} sees surge in Wikipedia edits",
            "Developing Story: Multiple updates to {} articles",
            "Trending Now: {} gaining attention across Wikipedia",
            "Alert: Rapid changes to {} information",
            "Watch: {} articles under heavy editing",
            "{} becomes hot topic on Wikipedia",
            "Investigation: Why {} is trending on Wikipedia",
            "Latest: {} sparks wave of Wikipedia updates"
        ]
        
        used_topics = set()
        for topic, items in sorted(topic_clusters.items(), key=lambda x: len(x[1]), reverse=True):
            if len(items) >= 2 and topic not in used_topics and len(headlines) < num_headlines:
                # Calculate importance score
                avg_sentiment = sum(e['sentiment'] for e in items) / len(items)
                
                # Choose template based on sentiment
                if avg_sentiment > 0.3:
                    template_idx = random.randint(0, len(headline_templates) - 1)
                elif avg_sentiment < -0.3:
                    template_idx = random.choice([3, 6])  # More urgent templates
                else:
                    template_idx = random.randint(0, len(headline_templates) - 1)
                
                headline = headline_templates[template_idx].format(topic.capitalize())
                
                headlines.append({
                    'headline': headline,
                    'topic': topic,
                    'edit_count': len(items),
                    'sentiment': avg_sentiment,
                    'size': self._calculate_size(len(items), avg_sentiment),
                    'color': self._calculate_color(avg_sentiment),
                    'articles': [e['title'] for e in items[:3]]
                })
                
                used_topics.add(topic)
        
        # Add some general headlines from individual articles
        for entry in self.entries[:10]:
            if len(headlines) >= num_headlines:
                break
            
            if entry['title'] not in [h.get('articles', [None])[0] for h in headlines]:
                headline = f"{entry['title']}: {self._summarize_edit(entry['edit'])}"
                headlines.append({
                    'headline': headline,
                    'topic': entry['title'],
                    'edit_count': 1,
                    'sentiment': entry['sentiment'],
                    'size': 'medium' if len(headline) < 50 else 'large',
                    'color': self._calculate_color(entry['sentiment']),
                    'articles': [entry['title']]
                })
        
        return headlines[:num_headlines]
    
    def _calculate_size(self, edit_count, sentiment):
        """Calculate bubble size based on edit count and sentiment"""
        if edit_count > 5:
            return 'large'
        elif edit_count > 3:
            return 'medium'
        elif edit_count > 1:
            return 'small'
        else:
            return 'tiny'
    
    def _calculate_color(self, sentiment):
        """Calculate color based on sentiment"""
        if sentiment > 0.4:
            return 'blue'
        elif sentiment > 0.2:
            return 'light-blue'
        elif sentiment > 0:
            return 'gold'
        elif sentiment > -0.2:
            return 'orange'
        elif sentiment > -0.4:
            return 'dark-red'
        else:
            return 'red'
    
    def _summarize_edit(self, edit_text):
        """Create a short summary of the edit"""
        # Take first meaningful part of the edit
        sentences = edit_text.split('.')
        if sentences:
            return sentences[0][:60] + "..."
        return edit_text[:60] + "..."
    
    def generate_json_output(self, output_file="wiki_news_data.json"):
        """Generate JSON file with all data for the web interface"""
        self.analyze_edits()
        mood, mood_score = self.get_overall_mood()
        headlines = self.generate_headlines(5)
        
        data = {
            'mood': mood,
            'mood_score': float(mood_score),
            'total_edits': len(self.entries),
            'time_window_minutes': 15,  # Simulated
            'headlines': headlines,
            'stats': {
                'total_articles': len(self.df),
                'avg_sentiment': float(sum(e['sentiment'] for e in self.entries) / len(self.entries)),
                'top_keywords': [{'word': word, 'count': count} for word, count in Counter(self.all_keywords).most_common(10)]
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"\n✅ Generated {output_file}")
        return data
    
    def print_report(self):
        """Print a console report"""
        self.analyze_edits()
        mood, mood_score = self.get_overall_mood()
        headlines = self.generate_headlines(5)
        
        print("\n" + "="*80)
        print("📰 WIKI-NEWS GENERATOR")
        print("="*80)
        print(f"\n🧠 Wikipedia's current mood: {mood.upper()} (score: {mood_score:.2f})")
        print(f"\n📊 Analyzed {len(self.entries)} edits from {len(self.df)} articles")
        
        print("\n" + "-"*80)
        print("🔥 TOP HEADLINES:")
        print("-"*80)
        
        for i, headline_data in enumerate(headlines, 1):
            print(f"\n{i}. {headline_data['headline']}")
            print(f"   📈 Based on {headline_data['edit_count']} edit(s)")
            print(f"   💡 Sentiment: {headline_data['sentiment']:.2f}")
            print(f"   🎨 Visual: {headline_data['size']} {headline_data['color']} bubble")
            if headline_data.get('articles'):
                print(f"   📄 Articles: {', '.join(headline_data['articles'][:2])}")
        
        print("\n" + "="*80 + "\n")


def main():
    """Main execution"""
    generator = WikiNewsGenerator()
    
    # Print console report
    generator.print_report()
    
    # Generate JSON for web interface
    data = generator.generate_json_output()
    
    print("\n💡 To view the web interface:")
    print("   Open: wiki-news.html in your browser")
    print("   Or run: python -m http.server 8080")
    print("   Then visit: http://localhost:8080/wiki-news.html\n")


if __name__ == "__main__":
    main()
