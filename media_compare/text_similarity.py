from __future__ import annotations

import math
import re
from collections import Counter

WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9][a-zA-ZÀ-ÿ0-9'’_-]*")

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


def article_similarity(title_a: str, body_a: str, title_b: str, body_b: str) -> float:
    body_counter_a = term_counter(body_a)
    body_counter_b = term_counter(body_b)
    title_counter_a = term_counter(title_a)
    title_counter_b = term_counter(title_b)

    body_cosine = cosine_similarity(body_counter_a, body_counter_b)
    title_cosine = cosine_similarity(title_counter_a, title_counter_b)
    keyword_jaccard = jaccard_similarity(set(body_counter_a), set(body_counter_b))

    return round((body_cosine * 0.60) + (title_cosine * 0.25) + (keyword_jaccard * 0.15), 4)
