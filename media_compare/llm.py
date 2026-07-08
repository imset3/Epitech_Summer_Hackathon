from __future__ import annotations

import json
import os
import re
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
            "description": (
                "A detailed recap paragraph compiling stable facts and disputed details. "
                "Use inline alternatives for volatile details in the exact format '(XX%) option 1 | (YY%) option 2'."
            ),
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
        "source_notes",
    ],
    "additionalProperties": False,
}


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
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


def _make_prompt(cluster: StoryCluster) -> str:
    payload = cluster.to_prompt_payload()
    return f"""
Compare these articles as reports about one possible news story.

Rules:
- Do not invent facts that are not in the supplied texts.
- Separate stable facts from volatile/disputed facts.
- Give more importance to sources with higher trust, but still note when several lower-weight sources agree.
- Prefer the story version that is both coherent and corroborated.
- Produce a real recap body, not just a headline. The body should compile the event, location, timing, consequences, official response, witness claims, uncertainty, and follow-up actions when present.
- The compiled_body should normally be 1 paragraph of 5 to 9 sentences. Use 2 paragraphs only if the story is dense.
- For disputed or volatile details, use inline alternatives in the compiled_body with this exact structure: "(XX%) option 1 | (YY%) option 2".
- Percentages are support estimates based on source trust/reach weights and corroboration inside this cluster. They are not mathematical proof.
- Example: "Fire at a chemical factory near Lyon: (60%) 15 injured | (12%) 2 dead and 13 injured, while a large smoke cloud spread around the site and authorities evacuated nearby streets."
- If a volatile element has more than two versions, put the two most important or most representative versions in option_1 and option_2.

Cluster data:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def analyze_cluster_with_api(cluster: StoryCluster, model: str | None = None) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("The openai package is not installed. Run: pip install -r requirements.txt") from exc

    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    selected_model = model or os.environ.get("OPENAI_MODEL", "gpt-5.5")

    response = client.responses.create(
        model=selected_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a careful media-analysis assistant. "
                    "You compare multiple reports of the same event and produce neutral, source-aware synthesis. "
                    "Your recap must compile details from all supplied reports and clearly mark volatile details."
                ),
            },
            {"role": "user", "content": _make_prompt(cluster)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "story_analysis",
                "schema": STORY_ANALYSIS_SCHEMA,
                "strict": True,
            }
        },
    )

    return json.loads(response.output_text)


def _support_percentages(cluster: StoryCluster) -> dict[str, float]:
    total = sum(article.source.support_weight for article in cluster.articles) or 1.0
    return {
        article.article_id: round((article.source.support_weight / total) * 100, 1)
        for article in cluster.articles
    }


def _first_sentences(text: str, limit: int = 2) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]
    return sentences[:limit]


def _extract_casualty_claims(cluster: StoryCluster) -> list[tuple[str, float, str]]:
    percentages = _support_percentages(cluster)
    claims: dict[str, tuple[float, list[str]]] = {}

    for article in cluster.articles:
        for sentence in _first_sentences(article.body, limit=10):
            claim = _casualty_claim(sentence)
            if claim is None:
                continue
            current_weight, sources = claims.get(claim, (0.0, []))
            claims[claim] = (
                current_weight + percentages[article.article_id],
                [*sources, article.source.name],
            )
            break

    sorted_claims = sorted(
        ((claim, weight, ", ".join(sources)) for claim, (weight, sources) in claims.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    return sorted_claims[:2]


def _make_dry_run_body(cluster: StoryCluster) -> tuple[str, list[dict[str, str]]]:
    sources = ", ".join(cluster.distinct_sources)
    lead_article = max(cluster.articles, key=lambda a: a.source.support_weight)
    lead = lead_article.title.rstrip(".")

    detail_sentences: list[str] = []
    seen: set[str] = set()
    for article in sorted(cluster.articles, key=lambda a: a.source.support_weight, reverse=True):
        for sentence in _first_sentences(article.body, limit=3):
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
        f" This dry-run recap is based on {len(cluster.articles)} local .txt file(s), "
        f"reported by {sources}, with weighted support {cluster.weighted_support:.2f} "
        f"and local similarity {cluster.avg_similarity:.2f}."
    )

    return body, volatile_elements


def analyze_cluster_dry_run(cluster: StoryCluster) -> dict[str, Any]:
    titles = [a.title for a in cluster.articles]
    sources = ", ".join(cluster.distinct_sources)
    first_title = titles[0] if titles else f"Story #{cluster.cluster_id}"
    body, volatile_elements = _make_dry_run_body(cluster)

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
        "source_notes": [f"{a.source.name}: {a.title}" for a in cluster.articles],
    }
