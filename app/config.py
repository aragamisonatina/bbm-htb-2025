
# app/config.py
from dataclasses import dataclass

STOPWORDS = {
    "wikipedia","wikiproject","project","article","articles","editor","editors","edited",
    "update","updates","revised","revision","page","pages","talk","section","content",
    "reference","references","citation","citations","category","categories","template","templates"
}

ADMIN_TERMS = {
    "talk","draft","notification","redirects","discussion","rfd","afd",
    "template","category","wikidata","citation","references","log","banner"
}

@dataclass(frozen=True)
class Settings:
    # Stream
    stream_url: str = "https://stream.wikimedia.org/v2/stream/mediawiki.recentchange"
    enwiki_only: bool = True

    # Per-edit generation
    max_words: int = 8                   # hard cap for per-edit title length
    print_errors: bool = True            # log LLM failures as they happen
    min_bytes_for_llm: int = 0           # if >0, only call LLM when delta >= this

    # LLM backend (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"
    temperature: float = 0.6             # slightly cooler for single-edit stability
    seed: int = 42
    num_ctx: int = 256                   # small context since it's per-edit
    num_gpu: int = 0
    request_timeout_s: int = 30

    # SSE retry/backoff
    sse_retry_base_s: int = 3
    sse_retry_max_s: int = 20

    allowed_namespaces: tuple = (0,)  # article namespace
    require_comment: bool = True
    min_title_len: int = 4
    min_byte_diff: int = 20
