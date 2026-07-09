from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .clustering import cluster_articles
from .llm import analyze_cluster
from .loader import load_articles
from .url_loader import load_articles_from_url_file
from .fetcher import fetch_articles_from_apis
from .reporting import cluster_summary_line, write_json_report, write_markdown_report
from .sources import load_sources


def _selected_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "local":
        return os.environ.get("LOCAL_LLM_MODEL", "gemma4:e4b")
    if provider == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if provider == "gemini":
        return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if provider == "nim":
        return os.environ.get("NVIDIA_NIM_MODEL", "meta/llama-3.1-8b-instruct")
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
        description="Compare article URLs or local .txt files, cluster same stories, and synthesize source-aware recaps with OpenAI or a local LLM.",
    )
    parser.add_argument("input", type=Path, nargs="?", default=None, help="A .txt file containing one article URL per line, or a folder containing legacy .txt articles")
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default=None,
        help="Query online APIs (Google News RSS, NewsAPI, GDELT, Brave Search) in real time to fetch and compare articles.",
    )
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
        help="Model name. OpenAI defaults to OPENAI_MODEL or gpt-4o-mini; local defaults to LOCAL_LLM_MODEL or gemma4:e4b",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "local", "dry-run", "gemini", "nim"],
        help="LLM provider: 'openai', 'local' (Ollama), 'gemini' (Google), 'nim' (NVIDIA), or 'dry-run'.",
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
        "--fetch-timeout",
        type=int,
        default=20,
        help="Seconds to wait when fetching each URL from a URL list file. Default: 20",
    )
    parser.add_argument(
        "--query-variants",
        type=int,
        default=5,
        help="Number of expanded search query variants to try for --query API search. Default: 5",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=60,
        help="Maximum unique article URLs to scrape for --query API search. Default: 60",
    )
    parser.add_argument(
        "--extractor",
        choices=["auto", "newspaper", "fallback"],
        default="auto",
        help="URL article extractor. auto tries newspaper3k first, then the fallback parser. Default: auto",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/report.md"),
        help="Markdown output path. Default: reports/report.md",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("reports/report.json"),
        help="JSON output path for website/front-end use. Default: reports/report.json",
    )
    parser.add_argument(
        "--min-articles",
        type=int,
        default=2,
        help="Minimum number of articles in a cluster to include in the reports. Default: 2",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass

    args = build_parser().parse_args(argv)

    if not args.input and not args.query:
        print("Error: You must provide either an input path or a search --query.", file=sys.stderr)
        return 2
    if args.input and args.query:
        print("Error: Cannot specify both an input path and a search --query.", file=sys.stderr)
        return 2

    if args.input and not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    sources = load_sources(args.sources)
    fetch_errors: list[str] = []
    articles = []
    input_kind = "folder"
    provider = "dry-run" if args.dry_run else (args.provider or os.environ.get("LLM_PROVIDER", "openai"))
    selected_model = _selected_model(provider, args.model)
    selected_model_arg = selected_model if selected_model != "n/a" else None

    if args.query:
        input_kind = "api-search"
        articles, fetch_errors = fetch_articles_from_apis(
            args.query,
            sources,
            timeout=args.fetch_timeout,
            extractor=args.extractor,
            config_path=args.sources,
            query_variants=args.query_variants,
            max_articles=args.max_articles,
            llm_provider=provider,
            llm_model=selected_model_arg,
            local_base_url=args.local_base_url,
        )
    elif args.input.is_dir():
        articles = load_articles(
            args.input,
            sources,
            llm_provider=provider,
            llm_model=selected_model_arg,
            local_base_url=args.local_base_url,
        )
    else:
        input_kind = "url-list"
        articles, fetch_errors = load_articles_from_url_file(
            args.input,
            sources,
            timeout=args.fetch_timeout,
            extractor=args.extractor,
            config_path=args.sources,
            llm_provider=provider,
            llm_model=selected_model_arg,
            local_base_url=args.local_base_url,
        )

    if fetch_errors:
        print("URL fetch/extraction warnings:", file=sys.stderr)
        for error in fetch_errors:
            print(f"- {error}", file=sys.stderr)
        print(file=sys.stderr)

    if not articles:
        if input_kind == "url-list":
            print("No readable article URLs were found in the input file.", file=sys.stderr)
        elif input_kind == "api-search":
            print(f"No articles retrieved from online APIs for query: '{args.query}'", file=sys.stderr)
        else:
            print("No .txt files found.", file=sys.stderr)
        return 1

    clusters = cluster_articles(articles, threshold=args.threshold)
    clusters_to_analyze = [c for c in clusters if len(c.articles) >= args.min_articles][: max(0, args.top)]

    if input_kind == "url-list":
        print(f"Loaded {len(articles)} article URL(s). Detected {len(clusters)} story cluster(s).")
        print(f"URL extractor: {args.extractor}")
    elif input_kind == "api-search":
        print(f"Fetched {len(articles)} article(s) via API search. Detected {len(clusters)} story cluster(s).")
        print(f"URL extractor: {args.extractor}")
    else:
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

    json_output_path = args.json_out
    if json_output_path.suffix.lower() != ".json":
        json_output_path = json_output_path.with_suffix(".json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_output_path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown_report(output_path, clusters, analyses)
    write_json_report(json_output_path, clusters, analyses)

    print(f"Wrote {output_path}")
    print(f"Wrote {json_output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
