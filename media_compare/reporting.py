from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .confidence import recap_confidence
from .models import StoryCluster


def cluster_summary_line(cluster: StoryCluster) -> str:
    titles = "; ".join(a.title for a in cluster.articles[:3])
    if len(cluster.articles) > 3:
        titles += "; ..."
    sources = ", ".join(cluster.distinct_sources)
    return (
        f"Story #{cluster.cluster_id} | articles={len(cluster.articles)} | "
        f"sources={sources} | weighted_support={cluster.weighted_support:.2f} | "
        f"similarity={cluster.avg_similarity:.2f} | coverage={cluster.similarity_coverage:.2f}\n"
        f"  {titles}"
    )


def _analysis_body(analysis: dict[str, Any]) -> str:
    return (
        analysis.get("compiled_body")
        or analysis.get("paragraph")
        or analysis.get("most_supported_version")
        or ""
    )


def _has_volatile_detail(item: dict[str, Any]) -> bool:
    return any(
        str(item.get(key, "")).strip()
        for key in ("option_1", "option_2", "reason")
    )



def _article_date(article: Any) -> str:
    if article.signals.dates:
        return article.signals.dates[0]
    return (
        article.metadata.get("date")
        or article.metadata.get("publication_date")
        or article.metadata.get("published_time")
        or ""
    )


def _article_to_json(article: Any) -> dict[str, Any]:
    return {
        "article_id": article.article_id,
        "source": article.source.name,
        "title": article.title,
        "url": article.metadata.get("url", ""),
        "date": _article_date(article),
        "locations": article.signals.locations,
        "extractor": article.metadata.get("extractor", ""),
        "extractor_fallback_reason": article.metadata.get("extractor_fallback_reason", ""),
        "body_char_count": len(article.body),
    }


def _empty_analysis(cluster: StoryCluster) -> dict[str, Any]:
    return {
        "cluster_id": cluster.cluster_id,
        "headline": "",
        "coherence_rating": cluster.avg_similarity,
        "most_supported_version": "",
        "compiled_body": "",
        "volatile_elements": [],
        "source_notes": [],
    }


def cluster_to_json(cluster: StoryCluster, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the website-friendly JSON shape used by the old report.json.

    Keep this schema deliberately close to the historical report format: the
    top-level report remains a list of cluster objects, and each cluster embeds
    its analysis and confidence data.
    """
    selected_analysis = analysis or _empty_analysis(cluster)
    return {
        "cluster_id": cluster.cluster_id,
        "avg_similarity": round(cluster.avg_similarity, 4),
        "avg_best_similarity": round(cluster.avg_best_similarity, 4),
        "similarity_coverage": round(cluster.similarity_coverage, 4),
        "guardrail_score": round(cluster.guardrail_score, 4),
        "guardrail_notes": cluster.guardrail_notes,
        "sources": cluster.distinct_sources,
        "articles": [_article_to_json(article) for article in cluster.articles],
        "analysis": selected_analysis,
        "confidence": recap_confidence(cluster, selected_analysis),
    }


def write_json_report(path: Path, clusters: list[StoryCluster], analyses: list[dict[str, Any]]) -> None:
    analysis_by_id = {item.get("cluster_id"): item for item in analyses}
    payload = [
        cluster_to_json(cluster, analysis_by_id.get(cluster.cluster_id))
        for cluster in clusters
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(path: Path, clusters: list[StoryCluster], analyses: list[dict[str, Any]]) -> None:
    analysis_by_id = {item.get("cluster_id"): item for item in analyses}
    lines: list[str] = ["# Media story comparison report", ""]

    for cluster in clusters:
        lines.append(f"## Story #{cluster.cluster_id}")
        lines.append("")
        lines.append(f"- Articles: {len(cluster.articles)}")
        lines.append(f"- Sources: {', '.join(cluster.distinct_sources)}")
        lines.append(f"- Weighted support: {cluster.weighted_support:.2f}")
        lines.append(f"- Average pair similarity: {cluster.avg_similarity:.2f}")
        lines.append(f"- Similarity coverage: {cluster.similarity_coverage:.2f}")
        lines.append(f"- Best-neighbour similarity: {cluster.avg_best_similarity:.2f}")
        lines.append(f"- Date/location guardrail score: {cluster.guardrail_score:.2f}")
        # Raw date/location signals are intentionally not printed here. They can be noisy
        # when an extractor includes page furniture; use the guardrail notes and JSON
        # article metadata for debugging instead.

        analysis = analysis_by_id.get(cluster.cluster_id)
        confidence = recap_confidence(cluster, analysis)
        lines.append(
            f"- Recap confidence: {confidence['label']} ({confidence['score']:.1f}/100) — "
            f"{confidence['recommendation']}"
        )
        lines.append("")

        if cluster.guardrail_notes:
            lines.append("**Date/location guardrails:**")
            for note in cluster.guardrail_notes:
                lines.append(f"- {note}")
            lines.append("")

        if analysis:
            lines.append(f"**Suggested headline:** {analysis.get('headline', '')}")
            lines.append("")
            body = _analysis_body(analysis)
            if body:
                lines.append(body)
                lines.append("")
            volatile = [
                item for item in analysis.get("volatile_elements", [])
                if isinstance(item, dict) and _has_volatile_detail(item)
            ]
            if volatile:
                lines.append("**Conflict / uncertain details:**")
                for item in volatile:
                    reason = str(item.get("reason", "")).strip()
                    lines.append(
                        f"- {item.get('element', 'detail')}: "
                        f"{item.get('option_1', '')} | {item.get('option_2', '')}"
                    )
                    if reason:
                        lines.append(f"  Reason: {reason}")
                lines.append("")
        else:
            lines.append("No API synthesis was generated for this story.")
            lines.append("")

        lines.append("**Articles in cluster:**")
        for article in cluster.articles:
            lines.append(f"- {article.source.name}: `{article.path}` — {article.title}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
