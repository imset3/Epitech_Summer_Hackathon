from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


import re

COMMON_ENGLISH_WORDS = {
    "the", "be", "to", "of", "and", "a", "in", "that", "have", "it", "for", "not",
    "on", "with", "as", "at", "this", "is", "was", "are", "were", "an", "they", "we"
}


def is_mostly_english(text: str) -> bool:
    """Check if the text is mostly English using ASCII letter ratio and common stopwords."""
    clean = text.strip().lower()
    if not clean:
        return True

    # Check ASCII letter ratio to catch CJK/Cyrillic
    ascii_letters = sum(1 for c in clean if c.isascii() and c.isalpha())
    total_letters = sum(1 for c in clean if c.isalpha())
    if total_letters == 0:
        return True
    ascii_ratio = ascii_letters / total_letters

    # Check common English stopwords to distinguish from other Latin-based languages (e.g. French, Spanish)
    tokens = set(re.findall(r"\b[a-z]+\b", clean))
    matches = tokens.intersection(COMMON_ENGLISH_WORDS)
    min_matches = 1 if len(tokens) < 10 else 2

    return ascii_ratio > 0.85 and len(matches) >= min_matches


def translate_to_english(text: str) -> str:
    """Translates non-English text to English using Gemini API.

    If the text is already mostly English or if the GEMINI_API_KEY is not set,
    it returns the text as-is.
    """
    clean_text = text.strip()
    if not clean_text:
        return ""

    if is_mostly_english(clean_text):
        return clean_text

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY not set. Skipping translation helper.", file=sys.stderr)
        return clean_text

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = (
        "Translate the following news article text into neutral English. "
        "Keep the translation faithful to the original details. "
        "Do not include any greeting, notes, or metadata in the output. "
        "Output ONLY the translated text:\n\n"
        f"{clean_text}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1
        }
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
            content = response_payload["candidates"][0]["content"]["parts"][0]["text"]
            return content.strip()
    except Exception as exc:
        print(f"Warning: Multilingual translation failed (falling back to original text): {exc}", file=sys.stderr)
        return clean_text
