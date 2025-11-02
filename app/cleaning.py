# app/cleaning.py
import re
from typing import Set
from config import STOPWORDS, ADMIN_TERMS

NS_PREFIXES: Set[str] = {
    "special","user","user talk","talk","wikipedia","file","template",
    "help","category","portal","book","draft","timedtext","module","mediawiki",
}
EXCLUDE_TOKENS: Set[str] = {"whatlinkshere","special","category","categories","wp"}

RE_LINKS  = re.compile(r"\[\[|\]\]|\{\{|\}\}")
RE_URL    = re.compile(r"http[s]?://\S+")
RE_SPACES = re.compile(r"\s+")
RE_NS     = re.compile(r"^([^:]+):(.*)$")
RE_NONLET_ASCII = re.compile(r"[^A-Za-z ]+")

def _collapse_spaces(s: str) -> str:
    return RE_SPACES.sub(" ", s).strip()

def _ascii_words_only(s: str) -> str:
    return _collapse_spaces(RE_NONLET_ASCII.sub(" ", s))

def _drop_excluded_tokens(text: str) -> str:
    return " ".join(w for w in text.split() if w.lower() not in EXCLUDE_TOKENS)

def normalize_title(title: str) -> str:
    t = (title or "").strip()
    m = RE_NS.match(t)
    if m and m.group(1).lower() in NS_PREFIXES:
        t = m.group(2)
    t = t.replace("/", " ")
    t = _ascii_words_only(t)
    return _drop_excluded_tokens(t)

def normalize_comment(comment: str) -> str:
    c = RE_LINKS.sub(" ", comment or "")
    c = RE_URL.sub(" ", c)
    c = _ascii_words_only(c)
    return _drop_excluded_tokens(c)

def strip_admin_markup(text: str) -> str:
    t = RE_LINKS.sub(" ", text or "")
    t = RE_URL.sub(" ", t)
    return _collapse_spaces(t)
