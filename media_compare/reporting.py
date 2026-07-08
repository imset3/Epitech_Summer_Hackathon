from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import StoryCluster


def cluster_summary_line(cluster: StoryCluster) -> str:
    titles = "; ".join(a.title for a in cluster.articles[:3])
    if len(cluster.articles) > 3:
        titles += "; ..."
    sources = ", ".join(cluster.distinct_sources)
    return (
        f"Story #{cluster.cluster_id} | files={len(cluster.articles)} | "
        f"sources={sources} | weighted_support={cluster.weighted_support:.2f} | "
        f"similarity={cluster.avg_similarity:.2f} | score={cluster.score:.2f}\n"
        f"  {titles}"
    )


def _analysis_body(analysis: dict[str, Any]) -> str:
    return (
        analysis.get("compiled_body")
        or analysis.get("paragraph")
        or analysis.get("most_supported_version")
        or ""
    )


def write_markdown_report(path: Path, clusters: list[StoryCluster], analyses: list[dict[str, Any]]) -> None:
    analysis_by_id = {item.get("cluster_id"): item for item in analyses}
    lines: list[str] = ["# Media story comparison report", ""]

    for cluster in clusters:
        lines.append(f"## Story #{cluster.cluster_id}")
        lines.append("")
        lines.append(f"- Files: {len(cluster.articles)}")
        lines.append(f"- Sources: {', '.join(cluster.distinct_sources)}")
        lines.append(f"- Weighted support: {cluster.weighted_support:.2f}")
        lines.append(f"- Local similarity: {cluster.avg_similarity:.2f}")
        lines.append(f"- Prototype score: {cluster.score:.2f}")
        lines.append("")

        analysis = analysis_by_id.get(cluster.cluster_id)
        if analysis:
            lines.append(f"**Suggested headline:** {analysis.get('headline', '')}")
            lines.append("")
            body = _analysis_body(analysis)
            if body:
                lines.append(body)
                lines.append("")
            volatile = analysis.get("volatile_elements", [])
            if volatile:
                lines.append("**Volatile elements:**")
                for item in volatile:
                    lines.append(
                        f"- {item.get('element', 'detail')}: "
                        f"{item.get('option_1', '')} | {item.get('option_2', '')}"
                    )
                lines.append("")
        else:
            lines.append("No API synthesis was generated for this story.")
            lines.append("")

        lines.append("**Files in cluster:**")
        for article in cluster.articles:
            lines.append(f"- {article.source.name}: `{article.path}` — {article.title}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
