from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from .models import StoryCluster

STORY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cluster_id": {"type": "integer"},
        "headline": {
            "type": "string",
            "description": "A concise headline for the shared story, not the whole recap.",
        },
        "coherence_rating": {
            "type": "number",
            "description": "0 to 1. Higher means the sources agree clearly on the same stable story.",
        },
        "most_supported_version": {
            "type": "string",
            "description": "A concise neutral version of the story, based on source trust and corroboration.",
        },
        "compiled_body": {
            "type": "string",
            "description": "A detailed recap paragraph compiling stable facts and disputed details.",
        },
        "volatile_elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "option_1": {"type": "string"},
                    "option_2": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["element", "option_1", "option_2", "reason"],
                "additionalProperties": False,
            },
        },
        "common_facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Stable facts corroborated by at least two independent sources in this cluster.",
        },
        "single_source_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Material claims that appear to come from only one source or one source family.",
        },
        "uncertain_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Claims that need more evidence, context, or external verification.",
        },
        "source_report_focus": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One short note per source describing what that outlet emphasized.",
        },
        "source_notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Brief notes about which sources support which parts.",
        },
    },
    "required": [
        "cluster_id",
        "headline",
        "coherence_rating",
        "most_supported_version",
        "compiled_body",
        "volatile_elements",
        "common_facts",
        "single_source_claims",
        "uncertain_claims",
        "source_report_focus",
        "source_notes",
    ],
    "additionalProperties": False,
}


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_POLLUTION_SENTENCE_RE = re.compile(r"\b(SECTIONS|TOP STORIES|ADVERTISEMENT|RELATED STORIES|NEWSLETTER|SUBSCRIBE|SIGN IN|LOG IN)\b", re.I)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_NUMBER_TOKEN = r"(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
_DEAD_RE = re.compile(rf"\b(?P<number>{_NUMBER_TOKEN})\s+(?:people\s+)?(?:died|dead|killed)\b", re.I)
_INJURED_RE = re.compile(rf"\b(?P<number>{_NUMBER_TOKEN})\s+(?:people\s+|others\s+)?(?:were\s+)?injured\b", re.I)


def _number_value(value: str) -> int | None:
    value = value.casefold()
    if value.isdigit():
        return int(value)
    return _NUMBER_WORDS.get(value)


def _casualty_claim(sentence: str) -> str | None:
    dead_match = _DEAD_RE.search(sentence)
    injured_match = _INJURED_RE.search(sentence)
    dead = _number_value(dead_match.group("number")) if dead_match else None
    injured = _number_value(injured_match.group("number")) if injured_match else None

    if dead is not None and injured is not None:
        return f"{dead} dead and {injured} injured"
    if injured is not None:
        return f"{injured} injured"
    if dead is not None:
        return f"{dead} dead"
    return None


def _volatile_claim_hints(cluster: StoryCluster) -> str:
    claims = _extract_casualty_claims(cluster)
    if len(claims) < 2:
        return ""

    lines = [
        "Locally detected volatile claim candidates:",
        *[
            f"- {claim} ({weight:.0f}% weighted support from {sources})"
            for claim, weight, sources in claims
        ],
    ]
    return "\n".join(lines)


def _make_prompt(cluster: StoryCluster) -> str:
    payload = cluster.to_prompt_payload()
    volatile_hints = _volatile_claim_hints(cluster)
    return f"""
Compare these article extracts as reports about one possible news story.

Rules:
- Do not invent facts that are not in the supplied article extracts.
- Separate stable facts from volatile/disputed facts.
- Never erase a conflict by choosing only the smoother or majority version.
- Give more importance to sources with higher trust, but still note when several lower-weight sources agree.
- Prefer the story version that is both coherent and corroborated.
- Use the supplied dates, years, and locations as guardrails: if articles share a broad theme but point to different times or places, lower coherence and say that more data is needed instead of pretending certainty.
- If location or date details conflict inside a cluster, mention that as uncertainty unless the texts clearly explain that one article is giving background context.
- Produce a real recap body, not just a headline. The body should compile the event, location, timing, consequences, official response, witness claims, uncertainty, and follow-up actions when present.
- The compiled_body should normally be 1 paragraph of 5 to 9 sentences. Use 2 paragraphs only if the story is dense.
- Put disputed or volatile details in volatile_elements so the report can display a separate conflict section.
- Put corroborated facts in common_facts. Each common fact should be supported by at least two independent sources in the cluster.
- Put claims with only one visible source in single_source_claims.
- Put weak, unresolved, or externally unverified claims in uncertain_claims.
- Put one source_report_focus item per major source, in the form "Source: what this outlet emphasized."
- In compiled_body, briefly mention that a conflict exists, but do not rely on the paragraph as the only place where the conflict appears.
- If locally detected volatile claim candidates are listed, include them in volatile_elements and mention the uncertainty in compiled_body.
- Percentages are support estimates based on source trust/reach weights and corroboration inside this cluster. They are not mathematical proof.
- Do not invent missing dates or locations. If they are absent, say the timing or location is not confirmed by the supplied article extracts.
- Do not attach percentages to source names or stable claims. Use percentages only inside volatile_elements options.
- Example: "Fire at a chemical factory near Lyon: (60%) 15 injured | (12%) 2 dead and 13 injured, while a large smoke cloud spread around the site and authorities evacuated nearby streets."
- If a volatile element has more than two versions, put the two most important or most representative versions in option_1 and option_2.

Cluster data:
{json.dumps(payload, ensure_ascii=False, indent=2)}

{volatile_hints}
""".strip()


def _system_prompt() -> str:
    return (
        "You are a careful media-analysis assistant. "
        "You compare multiple reports of the same event and produce neutral, source-aware synthesis. "
        "Your recap must compile details from all supplied reports and clearly mark volatile details. "
        "When sources disagree, preserve the disagreement instead of resolving it silently. "
        "Return only valid JSON that matches the requested schema."
    )


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(raw_text[start:end + 1])


_CONFLICT_HINT_RE = re.compile(
    r"\b(conflict|conflicting|disagree|disagrees|disagreement|differ|differs|different|disputed|uncertain|uncertainty|unclear|unconfirmed|not confirmed)\b",
    re.I,
)
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.I | re.S)


def _text_detected_volatile_elements(analysis: dict[str, Any]) -> list[dict[str, str]]:
    body = str(analysis.get("compiled_body") or analysis.get("paragraph") or "")
    if not body:
        return []

    for sentence in _first_sentences(body, limit=10):
        if _CONFLICT_HINT_RE.search(sentence):
            return [
                {
                    "element": "reported detail requiring source comparison",
                    "option_1": "Stable point: the core story is supported by the cluster",
                    "option_2": f"Unresolved point: {sentence}",
                    "reason": (
                        "The model described a conflict or uncertainty in the synthesis "
                        "but did not return it as a structured conflict item."
                    ),
                }
            ]
    return []


def _coerce_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    fence_match = _JSON_FENCE_RE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _humanize_value(value: Any) -> str:
    value = _coerce_jsonish(value)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(part for part in (_humanize_value(item) for item in value) if part)
    if isinstance(value, dict):
        for preferred_key in ("fact", "claim", "summary", "text", "description", "focus", "note", "reason"):
            preferred = _humanize_value(value.get(preferred_key))
            if preferred:
                source = _humanize_value(value.get("source") or value.get("publisher"))
                return f"{source}: {preferred}" if source else preferred
        parts = [
            f"{key}: {_humanize_value(item)}"
            for key, item in value.items()
            if _humanize_value(item)
        ]
        return "; ".join(parts)
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    value = _coerce_jsonish(value)
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [text for text in (_humanize_value(item) for item in value) if text]
    return [text] if (text := _humanize_value(value)) else []


def _normalize_volatile_elements(value: Any) -> list[dict[str, str]]:
    value = _coerce_jsonish(value)
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        text = _humanize_value(value)
        return [{
            "element": "reported detail requiring source comparison",
            "option_1": "",
            "option_2": text,
            "reason": "The model returned this uncertainty as unstructured text.",
        }] if text else []

    normalized_items: list[dict[str, str]] = []
    for item in value:
        item = _coerce_jsonish(item)
        if isinstance(item, dict):
            normalized_item = {
                "element": _humanize_value(item.get("element") or item.get("claim") or item.get("detail") or "detail"),
                "option_1": _humanize_value(item.get("option_1") or item.get("version_1") or item.get("supported") or ""),
                "option_2": _humanize_value(item.get("option_2") or item.get("version_2") or item.get("disputed") or ""),
                "reason": _humanize_value(item.get("reason") or item.get("note") or item.get("explanation") or ""),
            }
        else:
            text = _humanize_value(item)
            normalized_item = {
                "element": "reported detail requiring source comparison",
                "option_1": "",
                "option_2": text,
                "reason": "The model returned this uncertainty as unstructured text.",
            }
        if normalized_item["option_1"] or normalized_item["option_2"] or normalized_item["reason"]:
            normalized_items.append(normalized_item)
    return normalized_items


def _representative_article_notes(cluster: StoryCluster, limit: int = 6) -> list[str]:
    return [
        f"{article.source.name}: {article.title}"
        for article in cluster.representative_articles[:limit]
    ]


def _first_sentence(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    sentences = _first_sentences(value, limit=1)
    return sentences[0] if sentences else value


def _fill_analysis_fallbacks(normalized: dict[str, Any], cluster: StoryCluster) -> None:
    if not normalized["common_facts"]:
        if normalized["most_supported_version"]:
            normalized["common_facts"] = [normalized["most_supported_version"]]
        elif normalized["compiled_body"]:
            normalized["common_facts"] = [_first_sentence(normalized["compiled_body"])]
        elif cluster.articles:
            normalized["common_facts"] = [
                f"This cluster groups {len(cluster.articles)} article(s) from {cluster.source_count} independent source(s) around the same reported story."
            ]

    if not normalized["single_source_claims"]:
        source_counts = {
            article.source.name: sum(1 for candidate in cluster.articles if candidate.source.name == article.source.name)
            for article in cluster.articles
        }
        normalized["single_source_claims"] = [
            f"{article.source.name}: {article.title}"
            for article in cluster.articles
            if source_counts.get(article.source.name, 0) == 1
        ][:3]

    if not normalized["uncertain_claims"]:
        reasons = [
            item.get("reason", "")
            for item in normalized["volatile_elements"]
            if item.get("reason")
        ]
        normalized["uncertain_claims"] = reasons[:3] or cluster.guardrail_notes[:3]

    if not normalized["source_report_focus"]:
        normalized["source_report_focus"] = _representative_article_notes(cluster)

    if not normalized["source_notes"]:
        normalized["source_notes"] = normalized["source_report_focus"][:]


def _ensure_analysis_shape(analysis: dict[str, Any] | str, cluster: StoryCluster) -> dict[str, Any]:
    analysis = _coerce_jsonish(analysis)
    if not isinstance(analysis, dict):
        analysis = {}

    for key in ("compiled_body", "most_supported_version", "headline"):
        nested = _coerce_jsonish(analysis.get(key))
        if isinstance(nested, dict):
            analysis = {**analysis, **{nested_key: nested_value for nested_key, nested_value in nested.items() if nested_value}}

    defaults: dict[str, Any] = {
        "cluster_id": cluster.cluster_id,
        "headline": f"Story #{cluster.cluster_id}",
        "coherence_rating": cluster.avg_similarity,
        "most_supported_version": "",
        "compiled_body": "",
        "volatile_elements": [],
        "common_facts": [],
        "single_source_claims": [],
        "uncertain_claims": [],
        "source_report_focus": [],
        "source_notes": [],
    }
    normalized = {**defaults, **analysis}
    normalized["cluster_id"] = int(normalized.get("cluster_id") or cluster.cluster_id)
    normalized["headline"] = _humanize_value(normalized.get("headline")) or f"Story #{cluster.cluster_id}"
    normalized["most_supported_version"] = _humanize_value(normalized.get("most_supported_version"))
    normalized["compiled_body"] = _humanize_value(normalized.get("compiled_body"))
    for key in ("common_facts", "single_source_claims", "uncertain_claims", "source_report_focus", "source_notes"):
        normalized[key] = _normalize_string_list(normalized.get(key))
    normalized["volatile_elements"] = _normalize_volatile_elements(normalized.get("volatile_elements"))
    for detected_item in _detected_volatile_elements(cluster):
        if not any(item.get("element") == detected_item["element"] for item in normalized["volatile_elements"]):
            normalized["volatile_elements"].append(detected_item)
    if not normalized["volatile_elements"]:
        normalized["volatile_elements"].extend(_text_detected_volatile_elements(normalized))
    _fill_analysis_fallbacks(normalized, cluster)
    return normalized


def analyze_cluster_with_api(cluster: StoryCluster, model: str | None = None) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed. Run: pip install -r requirements.txt") from exc

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set.")
    client = OpenAI(api_key=api_key)
    selected_model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=selected_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _system_prompt()},
                    {"role": "user", "content": _make_prompt(cluster)},
                ],
                temperature=0.2,
                max_tokens=1500,
            )
            raw_text = response.choices[0].message.content or "{}"
            return _ensure_analysis_shape(json.loads(raw_text), cluster)
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "rate_limit" in exc_str.lower() or "RateLimitError" in type(exc).__name__:
                wait = 2 ** attempt * 5  # 5s, 10s, 20s
                print(f"OpenAI rate limit hit (attempt {attempt+1}/3). Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                last_exc = exc
            else:
                raise RuntimeError(f"OpenAI API error: {exc}") from exc
    raise RuntimeError(f"OpenAI API rate limit exceeded after retries: {last_exc}")


def analyze_cluster_with_local_llm(
    cluster: StoryCluster,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    selected_model = model or os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
    selected_base_url = (base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
    endpoint = f"{selected_base_url}/api/chat"
    prompt = (
        f"{_make_prompt(cluster)}\n\n"
        "Return only one JSON object with these keys: cluster_id, headline, coherence_rating, "
        "most_supported_version, compiled_body, volatile_elements, common_facts, "
        "single_source_claims, uncertain_claims, source_report_focus, source_notes."
    )
    payload = {
        "model": selected_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": 0.2,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach local LLM at {endpoint}. "
            "Start Ollama or set LOCAL_LLM_BASE_URL to a reachable server."
        ) from exc

    content = response_payload.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(f"Local LLM response did not include message.content: {response_payload}")
    return _ensure_analysis_shape(_parse_json_response(content), cluster)


def analyze_cluster_with_gemini(
    cluster: StoryCluster,
    model: str | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable not set.")

    selected_model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{selected_model}:generateContent?key={api_key}"

    system_instructions = _system_prompt()
    user_prompt = _make_prompt(cluster)
    full_text_prompt = (
        f"System Instructions:\n{system_instructions}\n\n"
        f"Analyze the following story cluster and return JSON matching the schema.\n\n"
        f"User Request:\n{user_prompt}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": full_text_prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    # Retry only Gemini rate limits. Other failures should be visible to the UI/CLI.
    response_payload: dict[str, Any] | None = None
    max_retries = 10
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                if attempt < max_retries - 1:
                    sleep_time = random.uniform(5.0, 10.0)
                    print(f"Warning: Gemini API Rate Limit (429) hit. Retrying in {sleep_time:.2f} seconds...", file=sys.stderr)
                    time.sleep(sleep_time)
                    continue

                fallback_headline = f"Reported Event: {cluster.articles[0].title}"
                fallback_compiled = (
                    f"This story is reported by {cluster.source_count} source(s) including {', '.join(cluster.distinct_sources)}. "
                    f"Gemini rate limits prevented full semantic synthesis, so this fallback only summarizes cluster metadata. "
                    f"Primary titles include: {'; '.join([a.title for a in cluster.articles[:3]])}."
                )
                return _ensure_analysis_shape({
                    "cluster_id": cluster.cluster_id,
                    "headline": fallback_headline,
                    "coherence_rating": cluster.avg_similarity,
                    "most_supported_version": fallback_headline,
                    "compiled_body": fallback_compiled,
                    "volatile_elements": [],
                    "source_notes": ["Synthesis fallback applied because Gemini returned HTTP 429 after retries."],
                }, cluster)

            raise RuntimeError(f"Gemini API HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Gemini API: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("Gemini API returned a non-JSON response.") from exc

    if response_payload is None:
        raise RuntimeError("Gemini API did not return a response payload.")

    try:
        content = response_payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected response structure from Gemini API: {response_payload}") from exc

    try:
        parsed = _parse_json_response(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini response was not valid analysis JSON: {content[:500]}") from exc

    return _ensure_analysis_shape(parsed, cluster)


def analyze_cluster_with_nim(
    cluster: StoryCluster,
    model: str | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("NVIDIA_NIM_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_NIM_API_KEY environment variable not set.")

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed. Run: pip install -r requirements.txt") from exc

    selected_model = model or os.environ.get("NVIDIA_NIM_MODEL", "meta/llama-3.1-8b-instruct")
    client = OpenAI(api_key=api_key, base_url="https://integrate.api.nvidia.com/v1")

    # Use NVIDIA NIM completion with JSON object response formatting
    response = client.chat.completions.create(
        model=selected_model,
        messages=[
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _make_prompt(cluster)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"}
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("NVIDIA NIM response did not include content.")

    return _ensure_analysis_shape(_parse_json_response(content), cluster)


def analyze_cluster(
    cluster: StoryCluster,
    provider: str = "openai",
    model: str | None = None,
    local_base_url: str | None = None,
) -> dict[str, Any]:
    if provider == "dry-run":
        return analyze_cluster_dry_run(cluster)
    if provider == "local":
        return analyze_cluster_with_local_llm(cluster, model=model, base_url=local_base_url)
    if provider == "openai":
        return analyze_cluster_with_api(cluster, model=model)
    if provider == "gemini":
        return analyze_cluster_with_gemini(cluster, model=model)
    if provider == "nim":
        return analyze_cluster_with_nim(cluster, model=model)
    raise ValueError(f"Unknown LLM provider: {provider}")


def _source_support_percentages(cluster: StoryCluster) -> dict[str, float]:
    source_weights = {
        article.source.name: article.source.support_weight
        for article in cluster.representative_articles
    }
    total = sum(source_weights.values()) or 1.0
    return {
        source_name: round((weight / total) * 100, 1)
        for source_name, weight in source_weights.items()
    }


def _first_sentences(text: str, limit: int = 2) -> list[str]:
    sentences: list[str] = []
    for sentence in _SENTENCE_RE.split(text.strip()):
        clean = sentence.strip()
        if not clean:
            continue
        if _POLLUTION_SENTENCE_RE.search(clean):
            break
        sentences.append(clean)
        if len(sentences) >= limit:
            break
    return sentences


def _extract_casualty_claims(cluster: StoryCluster) -> list[tuple[str, float, str]]:
    percentages = _source_support_percentages(cluster)
    claims: dict[str, tuple[float, list[str]]] = {}
    counted_sources: set[str] = set()

    for article in cluster.articles:
        if article.source.name in counted_sources:
            continue
        for sentence in _first_sentences(article.analysis_text, limit=10):
            claim = _casualty_claim(sentence)
            if claim is None:
                continue
            current_weight, sources = claims.get(claim, (0.0, []))
            claims[claim] = (
                current_weight + percentages.get(article.source.name, 0.0),
                [*sources, article.source.name],
            )
            counted_sources.add(article.source.name)
            break

    sorted_claims = sorted(
        ((claim, weight, ", ".join(sources)) for claim, (weight, sources) in claims.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return sorted_claims[:2]


def _detected_volatile_elements(cluster: StoryCluster) -> list[dict[str, str]]:
    claims = _extract_casualty_claims(cluster)
    if len(claims) < 2:
        return []

    return [
        {
            "element": "casualty count",
            "option_1": f"({claims[0][1]:.0f}%) {claims[0][0]}",
            "option_2": f"({claims[1][1]:.0f}%) {claims[1][0]}",
            "reason": f"Conflicting casualty claims were detected in {claims[0][2]} and {claims[1][2]}.",
        }
    ]


def _make_dry_run_body(cluster: StoryCluster) -> tuple[str, list[dict[str, str]]]:
    sources = ", ".join(cluster.distinct_sources)
    lead_article = max(cluster.articles, key=lambda a: a.source.support_weight)
    lead = lead_article.title.rstrip(".")

    detail_sentences: list[str] = []
    seen: set[str] = set()
    for article in sorted(cluster.articles, key=lambda a: a.source.support_weight, reverse=True):
        for sentence in _first_sentences(article.analysis_text, limit=3):
            clean = re.sub(r"\s+", " ", sentence).strip()
            key = clean.casefold()
            if key not in seen:
                seen.add(key)
                detail_sentences.append(clean)
            if len(detail_sentences) >= 5:
                break
        if len(detail_sentences) >= 5:
            break

    claims = _extract_casualty_claims(cluster)
    volatile_elements: list[dict[str, str]] = []
    if len(claims) >= 2:
        option_1 = f"({claims[0][1]:.0f}%) {claims[0][0]}"
        option_2 = f"({claims[1][1]:.0f}%) {claims[1][0]}"
        volatile_elements.append(
            {
                "element": "casualty count",
                "option_1": option_1,
                "option_2": option_2,
                "reason": f"Different casualty claims appear in {claims[0][2]} and {claims[1][2]}.",
            }
        )
        body = f"{lead}: {option_1} | {option_2}."
    else:
        body = f"{lead}."

    if detail_sentences:
        body += " " + " ".join(detail_sentences)

    body += (
        f" This dry-run recap is based on {len(cluster.articles)} article extract(s), "
        f"reported by {sources}, with weighted support {cluster.weighted_support:.2f} "
        f"and average pair similarity {cluster.avg_similarity:.2f}."
    )

    return body, volatile_elements


def analyze_cluster_dry_run(cluster: StoryCluster) -> dict[str, Any]:
    titles = [a.title for a in cluster.articles]
    sources = ", ".join(cluster.distinct_sources)
    first_title = titles[0] if titles else f"Story #{cluster.cluster_id}"
    body, volatile_elements = _make_dry_run_body(cluster)
    common_facts = [
        f"Reported by {cluster.source_count} independent source(s): {sources}.",
        f"Weighted source support is {cluster.weighted_support:.2f} with similarity coverage {cluster.similarity_coverage:.2f}.",
    ]
    source_frequencies = {
        article.source.name: sum(1 for candidate in cluster.articles if candidate.source.name == article.source.name)
        for article in cluster.articles
    }
    single_source_claims = [
        f"{article.source.name}: {article.title}"
        for article in cluster.articles
        if source_frequencies.get(article.source.name, 0) == 1
    ][:3]
    uncertain_claims = [
        item.get("reason", "")
        for item in volatile_elements
        if item.get("reason")
    ]
    source_report_focus = [
        f"{article.source.name}: {article.title}"
        for article in cluster.representative_articles
    ]

    return {
        "cluster_id": cluster.cluster_id,
        "headline": first_title,
        "coherence_rating": cluster.avg_similarity,
        "most_supported_version": (
            f"Dry run: this cluster is reported by {sources} with weighted support "
            f"{cluster.weighted_support:.2f}."
        ),
        "compiled_body": body,
        "volatile_elements": volatile_elements,
        "common_facts": common_facts,
        "single_source_claims": single_source_claims,
        "uncertain_claims": uncertain_claims,
        "source_report_focus": source_report_focus,
        "source_notes": [f"{a.source.name}: {a.title}" for a in cluster.articles],
    }
