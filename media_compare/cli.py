from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .clustering import cluster_articles
from .llm import analyze_cluster
from .loader import load_articles
from .reporting import cluster_summary_line, write_markdown_report
from .sources import load_sources


def _selected_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "local":
        return os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
    if provider == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-5.5")
    return "n/a"


def _local_endpoint(local_base_url: str | None) -> str:
    base_url = (local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
    return f"{base_url}/api/chat"


def _print_conflicts(analysis: dict) -> None:
    volatile = [
        item for item in analysis.get("volatile_elements", [])
        if isinstance(item, dict)
        and (
            str(item.get("option_1", "")).strip()
            or str(item.get("option_2", "")).strip()
            or str(item.get("reason", "")).strip()
        )
    ]
    if not volatile:
        return

    print("Conflict / uncertain details:")
    for item in volatile:
        print(f"- {item.get('element', 'detail')}: {item.get('option_1', '')} | {item.get('option_2', '')}")
        reason = str(item.get("reason", "")).strip()
        if reason:
            print(f"  Reason: {reason}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-compare",
        description="Compare local .txt files, cluster same stories, and synthesize source-aware recaps with OpenAI or a local LLM.",
    )
    parser.add_argument("folder", type=Path, help="Folder containing .txt articles")
    parser.add_argument(
        "--sources",
        type=Path,
        default=Path("config/sources.json"),
        help="JSON file containing source aliases and trust weights",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.22,
        help="Local similarity threshold used to group files into the same story",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum number of detected story clusters to analyze",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name. OpenAI defaults to OPENAI_MODEL or gpt-5.5; local defaults to LOCAL_LLM_MODEL or gemma4:e4b",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "local", "dry-run"],
        default=None,
        help="LLM provider. Defaults to LLM_PROVIDER or openai.",
    )
    parser.add_argument(
        "--local-base-url",
        type=str,
        default=None,
        help="Local Ollama-compatible server URL. Defaults to LOCAL_LLM_BASE_URL or http://localhost:11434",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call an LLM; only show clusters and produce local placeholder recap text",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/report.md"),
        help="Markdown output path. Default: reports/report.md",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="JSON output path for structured cluster statistics and LLM recaps.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass

    args = build_parser().parse_args(argv)

    if not args.folder.exists() or not args.folder.is_dir():
        print(f"Input folder not found: {args.folder}", file=sys.stderr)
        return 2

    sources = load_sources(args.sources)
    articles = load_articles(args.folder, sources)
    if not articles:
        print("No .txt files found.", file=sys.stderr)
        return 1

    clusters = cluster_articles(articles, threshold=args.threshold)
    clusters_to_analyze = clusters[: max(0, args.top)]
    provider = "dry-run" if args.dry_run else (args.provider or os.environ.get("LLM_PROVIDER", "openai"))
    selected_model = _selected_model(provider, args.model)

    print(f"Loaded {len(articles)} .txt article(s). Detected {len(clusters)} story cluster(s).")
    print(f"LLM provider: {provider}")
    print(f"LLM model: {selected_model}")
    if provider == "local":
        print(f"Local LLM endpoint: {_local_endpoint(args.local_base_url)}")
    print()
    for cluster in clusters:
        print(cluster_summary_line(cluster))
        print()

    analyses = []
    for cluster in clusters_to_analyze:
        analysis = analyze_cluster(
            cluster,
            provider=provider,
            model=args.model,
            local_base_url=args.local_base_url,
        )
        analyses.append(analysis)

        print(f"Synthesis for story #{cluster.cluster_id}:")
        print(analysis.get("compiled_body") or analysis.get("paragraph") or "")
        _print_conflicts(analysis)
        print()

    output_path = args.out
    if output_path.suffix.lower() != ".md":
        output_path = output_path.with_suffix(".md")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_report(output_path, clusters, analyses)
    print(f"Wrote {output_path}")

    if args.out_json:
        import json
        from .confidence import recap_confidence

        json_output_path = args.out_json
        json_output_path.parent.mkdir(parents=True, exist_ok=True)

        output_data = []
        for cluster, analysis in zip(clusters_to_analyze, analyses):
            conf = recap_confidence(cluster, analysis)
            output_data.append({
                "cluster_id": cluster.cluster_id,
                "score": cluster.score,
                "avg_similarity": cluster.avg_similarity,
                "avg_best_similarity": cluster.avg_best_similarity,
                "similarity_coverage": cluster.similarity_coverage,
                "guardrail_score": cluster.guardrail_score,
                "guardrail_notes": cluster.guardrail_notes,
                "sources": cluster.distinct_sources,
                "articles": [
                    {
                        "article_id": a.article_id,
                        "source": a.source.name,
                        "title": a.title,
                        "url": a.metadata.get("url", ""),
                        "date": a.signals.dates[0] if a.signals.dates else None,
                        "locations": a.signals.locations
                    } for a in cluster.articles
                ],
                "analysis": analysis,
                "confidence": conf
            })

        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"Wrote structured JSON to {json_output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
