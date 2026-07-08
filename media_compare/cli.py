from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .clustering import cluster_articles
from .llm import analyze_cluster_dry_run, analyze_cluster_with_api
from .loader import load_articles
from .reporting import cluster_summary_line, write_markdown_report
from .sources import load_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="media-compare",
        description="Compare local .txt files, cluster same stories, and synthesize source-aware recaps with the OpenAI API.",
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
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-5.5",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call the API; only show clusters and produce local placeholder recap text",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/report.md"),
        help="Markdown output path. Default: reports/report.md",
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

    print(f"Loaded {len(articles)} .txt article(s). Detected {len(clusters)} story cluster(s).")
    print()
    for cluster in clusters:
        print(cluster_summary_line(cluster))
        print()

    analyses = []
    for cluster in clusters_to_analyze:
        if args.dry_run:
            analysis = analyze_cluster_dry_run(cluster)
        else:
            analysis = analyze_cluster_with_api(cluster, model=args.model)
        analyses.append(analysis)

        print(f"Synthesis for story #{cluster.cluster_id}:")
        print(analysis.get("compiled_body") or analysis.get("paragraph") or "")
        print()

    output_path = args.out
    if output_path.suffix.lower() != ".md":
        output_path = output_path.with_suffix(".md")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_report(output_path, clusters, analyses)

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
