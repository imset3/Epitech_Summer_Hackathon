from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from functools import lru_cache

WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9가-힣][a-zA-ZÀ-ÿ0-9'’_-가-힣]*")

STOP_WORDS = {
    # French
    "alors", "apres", "avec", "avoir", "cette", "dans", "depuis", "des", "deux", "donc",
    "elle", "elles", "entre", "etre", "fait", "leur", "leurs", "mais", "nous", "pour",
    "plus", "quand", "que", "quel", "quelle", "sans", "selon", "sont", "sous", "tout",
    "tres", "une", "vers", "vous", "dont", "aux", "sur", "les", "est", "qui", "par",
    "pas", "son", "ses", "ont", "ete", "ete", "aux", "ces", "comme", "plusieurs", "aussi",
    # English
    "about", "after", "also", "and", "are", "been", "being", "but", "for", "from", "have",
    "into", "more", "not", "over", "said", "that", "the", "their", "there", "this", "were",
    "with", "would", "could", "should",
}


def tokenize(text: str) -> list[str]:
    words = [w.casefold().replace("’", "'") for w in WORD_RE.findall(text)]
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS]


def term_counter(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def cosine_similarity(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[word] * b[word] for word in common)
    norm_a = math.sqrt(sum(count * count for count in a.values()))
    norm_b = math.sqrt(sum(count * count for count in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@lru_cache(maxsize=1024)
def _get_embedding(text: str) -> list[float]:
    """Fetch dense embedding vector from Gemini Embedding API with caching."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []

    clean_text = text.strip()
    if not clean_text:
        return []

    # Use gemini-embedding-2 for dense representations
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={api_key}"
    payload = {
        "content": {
            "parts": [{"text": clean_text[:7500]}]
        }
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["embedding"]["values"]
    except Exception as exc:
        print(f"Warning: Failed to fetch embedding from Gemini (falling back to TF-IDF): {exc}", file=sys.stderr)
        return []


def _vector_cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def article_similarity(title_a: str, body_a: str, title_b: str, body_b: str) -> float:
    # 1. Try semantic embedding-based similarity first
    emb_a = _get_embedding(body_a)
    emb_b = _get_embedding(body_b)
    
    if emb_a and emb_b:
        emb_sim = _vector_cosine_similarity(emb_a, emb_b)
        return round(emb_sim, 4)

    # 2. Fallback to local TF-IDF term cosine similarity
    body_counter_a = term_counter(body_a)
    body_counter_b = term_counter(body_b)
    title_counter_a = term_counter(title_a)
    title_counter_b = term_counter(title_b)

    body_cosine = cosine_similarity(body_counter_a, body_counter_b)
    title_cosine = cosine_similarity(title_counter_a, title_counter_b)
    keyword_jaccard = jaccard_similarity(set(body_counter_a), set(body_counter_b))

    return round((body_cosine * 0.60) + (title_cosine * 0.25) + (keyword_jaccard * 0.15), 4)
