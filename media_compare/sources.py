from __future__ import annotations

import json
import os
import re
import sys
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


def _agentic_learn_source(domain: str, config_path: Path) -> SourceProfile | None:
    """Trigger Brave Search to check reputation, evaluate via Gemini, and auto-register domain."""
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not brave_key or not gemini_key:
        return None

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

    # 2. Evaluate using Gemini 2.5 Flash
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
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

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
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
        with urllib.request.urlopen(request, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            content_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            res = json.loads(content_text.strip())
            
            new_source = SourceProfile(
                name=res["name"],
                aliases=[domain, f"www.{domain}", res["name"].lower()],
                trust=float(res.get("trust", 0.5)),
                reach=float(res.get("reach", 0.3)),
                bias=res.get("bias", "untracked"),
                notes=res.get("notes", "Auto-learned via agentic search.")
            )
            
            # 3. Save permanently to sources.json if path exists
            if config_path.exists():
                try:
                    file_data = json.loads(config_path.read_text(encoding="utf-8"))
                    # Double check not already written
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
        print(f"Warning: Gemini evaluation failed for {domain}: {exc}", file=sys.stderr)
        return None


def detect_source(text_hint: str, sources: list[SourceProfile], config_path: Path | None = None) -> SourceProfile:
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
        default_config = config_path or Path("/Users/limseth/Projects/Epitech_Summer_Class/Hackathon/config/sources.json")
        learned = _agentic_learn_source(domain, default_config)
        if learned:
            sources.append(learned)
            return learned

    return next((s for s in sources if s.name == DEFAULT_UNKNOWN.name), DEFAULT_UNKNOWN)
