from __future__ import annotations

from typing import Any

from .models import StoryCluster


def _volatile_count(analysis: dict[str, Any] | None) -> int:
    if not analysis:
        return 0
    items = analysis.get("volatile_elements", [])
    if not isinstance(items, list):
        return 0
    return sum(
        1
        for item in items
        if isinstance(item, dict)
        and (
            str(item.get("option_1", "")).strip()
            or str(item.get("option_2", "")).strip()
            or str(item.get("reason", "")).strip()
        )
    )


def recap_confidence(cluster: StoryCluster, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Estimate whether a recap is ready to trust or needs more reporting.

    This is not truth detection. It measures how much the supplied local corpus supports
    one coherent recap: number of independent sources, trust/reach support, similarity
    coverage, and date/location guardrail consistency.
    """
    support_factor = min(cluster.weighted_support / 3.0, 1.0)
    source_factor = min(cluster.source_count / 3.0, 1.0)
    file_factor = min(len(cluster.articles) / 4.0, 1.0)

    # Local similarity drops on larger stories, so use coverage first and average-best
    # neighbor second instead of relying on all-pair average similarity.
    local_coherence = min(
        1.0,
        (cluster.similarity_coverage * 0.70) + (cluster.avg_best_similarity * 0.30),
    )

    guardrail_factor = cluster.guardrail_score or 0.50
    score = 100 * (
        (support_factor * 0.25)
        + (source_factor * 0.20)
        + (file_factor * 0.15)
        + (local_coherence * 0.25)
        + (guardrail_factor * 0.15)
    )

    volatility = _volatile_count(analysis)
    if volatility:
        score -= min(18.0, volatility * 6.0)
    if cluster.source_count < 2:
        score -= 12.0
    if len(cluster.articles) < 2:
        score -= 8.0

    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 75:
        label = "High"
        recommendation = "The recap is well supported by this local corpus. Still verify any volatile details before publishing."
    elif score >= 50:
        label = "Medium"
        recommendation = "Use the recap as a working version, but search for more data before treating it as settled."
    else:
        label = "Low"
        recommendation = "Treat the recap as a lead only. Search for more independent sources before relying on it."

    return {
        "score": score,
        "label": label,
        "recommendation": recommendation,
        "factors": {
            "support": round(support_factor, 3),
            "source_diversity": round(source_factor, 3),
            "article_count": round(file_factor, 3),
            "local_coherence": round(local_coherence, 3),
            "date_location_guardrails": round(guardrail_factor, 3),
            "volatile_elements": volatility,
        },
    }
