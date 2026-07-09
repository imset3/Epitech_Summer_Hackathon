from __future__ import annotations

import json
import os
import re
import sys
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .models import SourceProfile

DEFAULT_UNKNOWN = SourceProfile(
    name="Independent / Unknown",
    aliases=["independent", "unknown", "blog", "local"],
    trust=0.50,
    reach=0.30,
    bias="untracked",
    notes="Default when no known source is detected.",
)

_SOURCE_LEARNING_CACHE: dict[str, SourceProfile | None] = {}
_SOURCE_LEARNING_IN_PROGRESS: dict[str, threading.Event] = {}
_SOURCE_LEARNING_LOCK = threading.Lock()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold().strip()


def load_sources(config_path: Path) -> list[SourceProfile]:
    if not config_path.exists():
        return [DEFAULT_UNKNOWN]

    data = json.loads(config_path.read_text(encoding="utf-8"))
    sources: list[SourceProfile] = []
    for item in data.get("sources", []):
        sources.append(
            SourceProfile(
                name=item["name"],
                aliases=item.get("aliases", []),
                trust=float(item.get("trust", 0.5)),
                reach=float(item.get("reach", 0.3)),
                bias=item.get("bias", "untracked"),
                notes=item.get("notes", ""),
            )
        )
    return sources or [DEFAULT_UNKNOWN]


def _parse_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    return json.loads(text[start:end + 1])


def _evaluate_reputation_with_selected_llm(
    prompt: str,
    provider: str,
    model: str | None = None,
    local_base_url: str | None = None,
) -> dict:
    if provider == "dry-run":
        raise RuntimeError("dry-run provider does not evaluate source reputation.")

    if provider == "local":
        selected_model = model or os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
        selected_base_url = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
        endpoint = f"{selected_base_url}/api/chat"
        payload = {
            "model": selected_model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": "You evaluate publisher reputation and return only valid JSON."},
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
        return _parse_json_object(response_payload.get("message", {}).get("content", ""))

    if provider == "openai":
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
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You evaluate publisher reputation and return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        return _parse_json_object(response.choices[0].message.content or "")

    if provider == "nim":
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
                {"role": "system", "content": "You evaluate publisher reputation and return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return _parse_json_object(response.choices[0].message.content or "")

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not set.")
    selected_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={gemini_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    content_text = response_payload["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_object(content_text.strip())


def _fallback_source_for_domain(domain: str) -> SourceProfile:
    name = domain.removeprefix("www.")
    return SourceProfile(
        name=name,
        aliases=[domain, name],
        trust=0.60,
        reach=0.40,
        bias="untracked",
        notes="Dynamically detected source; reputation LLM evaluation was not available.",
    )


def _agentic_learn_source(
    domain: str,
    config_path: Path,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    local_base_url: str | None = None,
) -> SourceProfile | None:
    """Check reputation with Brave Search, evaluate via the active LLM, and auto-register domain."""
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not brave_key:
        return None
    selected_provider = llm_provider or os.environ.get("LLM_PROVIDER", "gemini")

    print(f"Agentic learning: Researching publisher reputation for domain: '{domain}' ...")

    # 1. Search reputation using Brave Search
    encoded_query = urllib.parse.quote(f"{domain} media bias fact check reliability")
    url = f"https://api.search.brave.com/res/v1/web/search?q={encoded_query}&count=3"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
        method="GET"
    )
    
    snippets = []
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("web", {}).get("results", [])
            for res in results:
                snippets.append(f"- {res.get('title')}: {res.get('description')}")
    except Exception as exc:
        print(f"Warning: Brave Search lookup failed for {domain}: {exc}", file=sys.stderr)
        return None

    prompt = (
        f"Based on the following search results about the publisher domain '{domain}', "
        "evaluate its factual reporting reliability (trust: float between 0.0 and 1.0, where 0.9+ is highly factual like Reuters/AP, 0.7-0.85 is mainstream, 0.5-0.6 is low factual/biased, 0.2 is fake news/conspiracy), "
        "reach/audience size (reach: float between 0.0 and 1.0), "
        "political bias (bias: 'left', 'left-center', 'center', 'right-center', 'right', 'untracked'), "
        "and write a short 1-sentence note (notes) summarizing its reputation.\n"
        "If the search snippets are empty or provide no info, evaluate the domain based on your own knowledge. "
        "Never return 0 for trust or reach; use reasonable defaults (e.g. trust=0.60, reach=0.40) if unknown.\n"
        "Return ONLY a JSON object matching this schema: "
        "{'name': string, 'trust': float, 'reach': float, 'bias': string, 'notes': string}.\n\n"
        f"Search Snippets:\n" + "\n".join(snippets)
    )

    try:
        if selected_provider == "local":
            # Fast-fail: check Ollama reachability before spending 20s on timeout
            _base = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
            try:
                urllib.request.urlopen(f"{_base}/api/tags", timeout=2).close()
            except Exception:
                print(f"Warning: Skipping source reputation for {domain} — Ollama is not reachable.", file=sys.stderr)
                return _fallback_source_for_domain(domain)

        res = _evaluate_reputation_with_selected_llm(
            prompt,
            provider=selected_provider,
            model=llm_model,
            local_base_url=local_base_url,
        )

        new_source = SourceProfile(
            name=str(res.get("name") or domain.removeprefix("www.")),
            aliases=[domain, f"www.{domain}", str(res.get("name") or domain).lower()],
            trust=float(res.get("trust", 0.5)),
            reach=float(res.get("reach", 0.3)),
            bias=res.get("bias", "untracked"),
            notes=res.get("notes", f"Auto-learned via {selected_provider} reputation search.")
        )

        if config_path.exists():
            try:
                file_data = json.loads(config_path.read_text(encoding="utf-8"))
                if not any(normalize(new_source.name) == normalize(src["name"]) for src in file_data.get("sources", [])):
                    file_data.setdefault("sources", []).append({
                        "name": new_source.name,
                        "aliases": new_source.aliases,
                        "trust": new_source.trust,
                        "reach": new_source.reach,
                        "bias": new_source.bias,
                        "notes": new_source.notes
                    })
                    config_path.write_text(json.dumps(file_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    print(f"Agentic learning: Registered new publisher '{new_source.name}' successfully in config/sources.json.")
            except Exception as exc:
                print(f"Warning: Failed to update config/sources.json: {exc}", file=sys.stderr)

        return new_source
    except Exception as exc:
        print(f"Warning: Source reputation evaluation failed for {domain} with {selected_provider}: {exc}", file=sys.stderr)
        return _fallback_source_for_domain(domain)


def detect_source(
    text_hint: str,
    sources: list[SourceProfile],
    config_path: Path | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    local_base_url: str | None = None,
) -> SourceProfile:
    hint = normalize(text_hint.replace("_", " ").replace("-", " "))
    matches: list[tuple[int, int, SourceProfile]] = []
    for source in sources:
        candidates = [source.name, *source.aliases]
        for candidate in candidates:
            normalized_candidate = normalize(candidate)
            index = hint.find(normalized_candidate)
            if index >= 0:
                matches.append((index, -len(normalized_candidate), source))
                break
    if matches:
        return min(matches, key=lambda match: (match[0], match[1]))[2]
        
    # Agentic Source Learning Fallback
    # Extract domain from hint
    domain_match = re.search(r"https?://(?:www\.)?([^/]+)", text_hint)
    if domain_match:
        domain = domain_match.group(1).lower()
        if config_path is not None:
            owner = False
            with _SOURCE_LEARNING_LOCK:
                if domain in _SOURCE_LEARNING_CACHE:
                    learned = _SOURCE_LEARNING_CACHE[domain]
                    if learned:
                        sources.append(learned)
                        return learned
                    return next((s for s in sources if s.name == DEFAULT_UNKNOWN.name), DEFAULT_UNKNOWN)

                event = _SOURCE_LEARNING_IN_PROGRESS.get(domain)
                if event is None:
                    event = threading.Event()
                    _SOURCE_LEARNING_IN_PROGRESS[domain] = event
                    owner = True

            if owner:
                try:
                    learned = _agentic_learn_source(
                        domain,
                        config_path,
                        llm_provider=llm_provider,
                        llm_model=llm_model,
                        local_base_url=local_base_url,
                    )
                finally:
                    with _SOURCE_LEARNING_LOCK:
                        _SOURCE_LEARNING_CACHE[domain] = locals().get("learned")
                        _SOURCE_LEARNING_IN_PROGRESS.pop(domain, None)
                        event.set()
            else:
                event.wait(timeout=25)
                with _SOURCE_LEARNING_LOCK:
                    learned = _SOURCE_LEARNING_CACHE.get(domain)

            if learned:
                sources.append(learned)
                return learned

    return next((s for s in sources if s.name == DEFAULT_UNKNOWN.name), DEFAULT_UNKNOWN)
