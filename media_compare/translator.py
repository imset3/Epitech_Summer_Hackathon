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


def _gemini_translate(prompt: str, model: str | None = None) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set.")

    selected_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    return response_payload["candidates"][0]["content"]["parts"][0]["text"].strip()


def _local_translate(prompt: str, model: str | None = None, local_base_url: str | None = None) -> str:
    selected_model = model or os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
    selected_base_url = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
    endpoint = f"{selected_base_url}/api/chat"
    payload = {
        "model": selected_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You translate news text faithfully into neutral English."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    return response_payload.get("message", {}).get("content", "").strip()


def _openai_translate(prompt: str, model: str | None = None) -> str:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed.") from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set.")
    selected_model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": "You translate news text faithfully into neutral English."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    return (response.choices[0].message.content or "").strip()


def _nim_translate(prompt: str, model: str | None = None) -> str:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed.") from exc

    api_key = os.environ.get("NVIDIA_NIM_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_NIM_API_KEY not set.")
    selected_model = model or os.environ.get("NVIDIA_NIM_MODEL", "meta/llama-3.1-8b-instruct")
    client = OpenAI(api_key=api_key, base_url="https://integrate.api.nvidia.com/v1")
    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": "You translate news text faithfully into neutral English."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return (response.choices[0].message.content or "").strip()


def translate_to_english(
    text: str,
    provider: str | None = None,
    model: str | None = None,
    local_base_url: str | None = None,
) -> str:
    """Translate non-English article text using the active LLM provider."""
    clean_text = text.strip()
    if not clean_text:
        return ""

    if is_mostly_english(clean_text):
        return clean_text

    selected_provider = provider or os.environ.get("LLM_PROVIDER", "gemini")
    if selected_provider == "dry-run":
        return clean_text

    # For local (Ollama): do a quick 2s connectivity check before attempting translation.
    # If Ollama is not running, skip translation immediately to avoid 20s hang per article.
    if selected_provider == "local":
        import urllib.request as _ureq
        _base = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
        try:
            _ureq.urlopen(f"{_base}/api/tags", timeout=2).close()
        except Exception:
            return clean_text  # Ollama unreachable — skip silently

    prompt = (
        "Translate the following news article text into neutral English. "
        "Keep the translation faithful to the original details. "
        "Do not include any greeting, notes, or metadata in the output. "
        "Output ONLY the translated text:\n\n"
        f"{clean_text}"
    )

    try:
        if selected_provider == "local":
            translated = _local_translate(prompt, model=model, local_base_url=local_base_url)
        elif selected_provider == "openai":
            translated = _openai_translate(prompt, model=model)
        elif selected_provider == "nim":
            translated = _nim_translate(prompt, model=model)
        else:
            translated = _gemini_translate(prompt, model=model)
        return translated or clean_text
    except Exception as exc:
        print(
            f"Warning: Multilingual translation failed with provider '{selected_provider}' "
            f"(falling back to original text): {exc}",
            file=sys.stderr,
        )
        return clean_text
