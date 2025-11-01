"""
Real-time Wikipedia Edit Stream → Ollama Headlines Server
Connects to Wikipedia EventStreams, generates headlines via Ollama,
and sends them to the React frontend via Server-Sent Events (SSE).
"""

import json
import re
import time
import textwrap
import requests
from collections import Counter
from threading import Thread, Lock
from queue import Queue, Empty
from flask import Flask, Response, jsonify
from flask_cors import CORS

# ==================== Configuration ====================
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:1b"
WIKIPEDIA_STREAM_URL = "https://stream.wikimedia.org/v2/stream/recentchange"

STOPWORDS = {
    "wikipedia", "wikiproject", "project", "article", "articles", "editor", "editors", "edited",
    "update", "updates", "revised", "revision", "page", "pages", "talk", "section", "content",
    "reference", "references", "citation", "citations", "category", "categories", "template", "templates"
}

ADMIN_TERMS = {
    "talk", "draft", "notification", "redirects", "discussion", "rfd", "afd",
    "template", "category", "wikidata", "citation", "references", "log", "banner"
}

BAN_TERMS = {"wikipedia", "wikiproject", "wikiprojects", "talk:", "draft talk:", "[[", "]]", "redirects for discussion"}

# ==================== Flask App ====================
app = Flask(__name__)
CORS(app)  # Enable CORS for React app

# Global state
clients = []
clients_lock = Lock()
edit_queue = Queue()
headline_cache = {}  # Cache generated headlines to avoid regenerating

# ==================== Helper Functions ====================

def _strip_admin_markup(text: str) -> str:
    """Remove Wikipedia admin markup and noise"""
    t = str(text)
    t = re.sub(r"\b(Talk|Draft talk|Draft|User talk|Category|Template):", "", t, flags=re.I)
    t = re.sub(r"\[\[|\]\]|\{{2,}|\}{2,}", "", t)
    t = re.sub(r"http[s]?://\S+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def _clean_headline(h):
    """Clean and format generated headline"""
    h = _strip_admin_markup(h)
    h = re.sub(r"^[\-\•\s]+", "", h).strip().strip('""\"\' ').rstrip(".")
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\bwikiprojects?\b", "projects", h, flags=re.I)
    h = re.sub(r"\bwikipedia\b", "the encyclopedia", h, flags=re.I)
    h = re.sub(r"\btalk:\b", "", h, flags=re.I)
    h = re.sub(r"\bredirects?\b.*", "", h, flags=re.I)
    words = h.split()
    h = " ".join(words[:12]) if len(words) > 12 else h
    return h.strip(" -:").strip()

def _looks_like_headline(h):
    """Validate if text looks like a proper headline"""
    if not h or len(h.split()) < 2 or len(h) < 8:
        return False
    low = h.lower()
    if any(b in low for b in BAN_TERMS):
        return False
    if re.search(r"\b(notification|discussion|rfd|afd|banner|log)\b", low):
        return False
    return True

def _tiny_context(edit_data, max_chars=280):
    """Build concise context from edit data"""
    words = []
    text = f"{edit_data.get('title', '')} {edit_data.get('comment', '')}"
    txt = _strip_admin_markup(text)
    
    for w in re.findall(r"\b[a-zA-Z]{5,}\b", txt):
        wl = w.lower()
        if wl not in STOPWORDS and wl not in ADMIN_TERMS:
            words.append(wl)
    
    common = ", ".join([w for w, _ in Counter(words).most_common(10)])
    blob = f"Article: {edit_data.get('title', 'Unknown')}\nCommon terms: {common}"
    return blob[:max_chars]

def generate_headline_ollama(edit_data):
    """Generate a headline for an edit using Ollama"""
    
    # Check cache first
    cache_key = edit_data.get('title', '')
    if cache_key in headline_cache:
        return headline_cache[cache_key]
    
    system = (
        "You are a news headline writer. Create a single, concise, engaging headline "
        "about a Wikipedia article being edited. Rules: present tense; ≤10 words; compelling but accurate; "
        "DO NOT mention 'Wikipedia', 'WikiProject', 'Talk', 'Draft', or 'Redirects'. "
        "Focus on the article's SUBJECT MATTER as if reporting news about that topic. "
        "Make it sound like a real news headline. "
        "RESPOND ONLY WITH the headline. Headline: "
    )
    
    user = textwrap.dedent(f"""
        Article being edited: {edit_data.get('title', 'Unknown')}
        Edit size: {edit_data.get('changeSize', 0)} bytes
        Context: {_tiny_context(edit_data)}
        
        Generate ONE headline about this article:
    """).strip()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"<<SYS>>{system}<<SYS>>\n\n{user}",
        "options": {
            "temperature": 0.8,
            "seed": None,
            "num_ctx": 512,
            "num_gpu": 0
        },
        "stream": False
    }

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=30)
        if r.status_code != 200:
            print(f"❌ Ollama error {r.status_code}: {r.text[:200]}")
            return None
        
        content = r.json().get("response", "").strip()
        
        # Clean up the response
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        for line in lines:
            headline = _clean_headline(line)
            if _looks_like_headline(headline):
                # Cache the result
                headline_cache[edit_data.get('title', '')] = headline
                return headline
        
        return None
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Ollama at {OLLAMA_HOST}")
        return None
    except Exception as e:
        print(f"❌ Error generating headline: {e}")
        return None

# ==================== SSE Stream ====================

def event_stream():
    """Server-Sent Events stream for sending edits with headlines to clients"""
    q = Queue()
    with clients_lock:
        clients.append(q)
    
    try:
        while True:
            edit_with_headline = q.get()
            if edit_with_headline is None:
                break
            yield f"data: {json.dumps(edit_with_headline)}\n\n"
    finally:
        with clients_lock:
            clients.remove(q)

@app.route('/stream')
def stream():
    """SSE endpoint for clients to connect to"""
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "ollama_model": OLLAMA_MODEL})

# ==================== Wikipedia Stream Processing ====================

def process_wikipedia_stream():
    """Connect to Wikipedia EventStreams and process edits"""
    print(f"🔗 Connecting to Wikipedia EventStreams...")
    
    while True:
        try:
            print("📡 Opening stream connection...")
            response = requests.get(WIKIPEDIA_STREAM_URL, stream=True, timeout=None, headers={'Accept': 'text/event-stream'})
            
            print("✅ Connected to Wikipedia EventStreams")
            
            # Process line by line
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                    
                if line.startswith('data: '):
                    data_str = line[6:]  # Remove 'data: ' prefix
                    try:
                        data = json.loads(data_str)
                        
                        # Filter for meaningful edits
                        if (data.get('wiki') == 'enwiki' and
                            data.get('namespace') == 0 and
                            data.get('type') == 'edit' and
                            data.get('title') and
                            not data.get('bot') and
                            len(data.get('title', '')) > 3):
                            
                            changeSize = (data.get('length', {}).get('new', 0) - 
                                        data.get('length', {}).get('old', 0))
                            
                            if abs(changeSize) > 20:
                                print(f"📥 Queuing: {data.get('title')[:40]}...")
                                edit_queue.put({
                                    'title': data.get('title'),
                                    'user': data.get('user', 'Anonymous'),
                                    'comment': data.get('comment', ''),
                                    'changeSize': changeSize,
                                    'timestamp': data.get('timestamp'),
                                    'wiki': data.get('wiki', 'enwiki')
                                })
                    
                    except json.JSONDecodeError as e:
                        continue
                    except Exception as e:
                        print(f"⚠️ Error processing edit: {e}")
                        continue
        
        except KeyboardInterrupt:
            print("\n👋 Shutting down...")
            break
        except Exception as e:
            print(f"❌ Stream error: {e}")
            print("🔄 Reconnecting in 5 seconds...")
            time.sleep(5)

def process_edit_queue():
    """Process edits from queue and generate headlines"""
    print("🤖 Starting headline generator...")
    
    while True:
        try:
            # Get edit from queue (blocks until available)
            edit_data = edit_queue.get(timeout=1)
            
            title_preview = edit_data['title'][:50] if len(edit_data['title']) > 50 else edit_data['title']
            print(f"📝 Processing: {title_preview}...")
            
            # Generate headline using Ollama
            headline = generate_headline_ollama(edit_data)
            
            if headline:
                print(f"✨ Generated: {headline}")
                edit_data['generatedHeadline'] = headline
            else:
                # Fallback to article title if generation fails
                print(f"⚠️ Using fallback for: {title_preview}")
                edit_data['generatedHeadline'] = edit_data['title'][:60]
            
            # Send to all connected clients
            with clients_lock:
                for client_queue in clients:
                    try:
                        client_queue.put(edit_data)
                    except:
                        pass
        
        except Empty:
            # No edit in queue, just continue
            time.sleep(0.1)
        except Exception as e:
            print(f"⚠️ Queue processing error: {e}")
            time.sleep(0.1)

# ==================== Main ====================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 WIKI-NEWS REAL-TIME HEADLINE SERVER")
    print("="*60)
    print(f"📡 Wikipedia Stream: {WIKIPEDIA_STREAM_URL}")
    print(f"🤖 Ollama: {OLLAMA_HOST} (model: {OLLAMA_MODEL})")
    print(f"🌐 Server will start on: http://localhost:5001")
    print("="*60 + "\n")
    
    # Test Ollama connection
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if r.status_code == 200:
            print("✅ Ollama is running and accessible")
        else:
            print("⚠️ Ollama connection issue - headlines may not generate")
    except:
        print("❌ WARNING: Cannot connect to Ollama!")
        print(f"   Make sure Ollama is running: ollama serve")
        print(f"   And model is available: ollama pull {OLLAMA_MODEL}")
    
    # Start background threads
    wiki_thread = Thread(target=process_wikipedia_stream, daemon=True)
    wiki_thread.start()
    
    processor_thread = Thread(target=process_edit_queue, daemon=True)
    processor_thread.start()
    
    # Start Flask server
    print("\n🌐 Starting web server...")
    app.run(host='0.0.0.0', port=5001, threaded=True)
