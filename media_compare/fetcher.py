from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .models import Article, SourceProfile
from .url_loader import fetch_article_from_url, ArticleFetchError
from .translator import translate_to_english


def _query_news_api(query: str, limit: int) -> dict[str, dict[str, str]]:
    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        print("Warning: NEWS_API_KEY not set. Skipping NewsAPI.", file=sys.stderr)
        return {}

    encoded_query = urllib.parse.quote(query)
    url = f"https://newsapi.org/v2/everything?q={encoded_query}&pageSize={limit}&apiKey={api_key}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "media-compare-fetcher"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data.get("status") != "ok":
                print(f"Warning: NewsAPI error: {data.get('message')}", file=sys.stderr)
                return {}
            results = {}
            for art in data.get("articles", []):
                article_url = art.get("url")
                if article_url:
                    results[article_url] = {
                        "title": art.get("title", "") or "",
                        "description": art.get("description", "") or art.get("content", "") or "",
                        "source": art.get("source", {}).get("name", "Unknown") or "Unknown",
                        "image_url": art.get("urlToImage", "") or "",
                    }
            return results
    except Exception as exc:
        print(f"Warning: Failed to query NewsAPI: {exc}", file=sys.stderr)
        return {}


def _query_brave_search(query: str, limit: int) -> dict[str, dict[str, str]]:
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        print("Warning: BRAVE_SEARCH_API_KEY not set. Skipping Brave Search.", file=sys.stderr)
        return {}

    encoded_query = urllib.parse.quote(query)
    url = f"https://api.search.brave.com/res/v1/news/search?q={encoded_query}&count={limit}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": "media-compare-fetcher"
        },
        method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            raw_results = data.get("results", [])
            results = {}
            for res in raw_results:
                article_url = res.get("url")
                if article_url:
                    results[article_url] = {
                        "title": res.get("title", "") or "",
                        "description": res.get("description", "") or "",
                        "source": res.get("page_fields", {}).get("source", "") or urllib.parse.urlparse(article_url).netloc,
                        "image_url": res.get("thumbnail", {}).get("src", "") or "",
                    }
            return results
    except Exception as exc:
        print(f"Warning: Failed to query Brave Search: {exc}", file=sys.stderr)
        return {}


def _query_gdelt(query: str, limit: int) -> dict[str, dict[str, str]]:
    # GDELT Doc API: No API key required. Implement a 2-attempt retry with backoff.
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={encoded_query}&mode=artlist&format=json&maxrecords={limit}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "media-compare-fetcher"},
        method="GET"
    )
    
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw_data = response.read().decode("utf-8")
                if not raw_data.strip():
                    return {}
                data = json.loads(raw_data)
                results = {}
                for art in data.get("articles", []):
                    article_url = art.get("url")
                    if article_url:
                        results[article_url] = {
                            "title": art.get("title", "") or "",
                            "description": "",
                            "source": art.get("source", "") or urllib.parse.urlparse(article_url).netloc,
                            "image_url": art.get("socialimage", "") or art.get("image", "") or "",
                        }
                return results
        except Exception as exc:
            if attempt == 0:
                # Wait 1.5 seconds and retry once
                time.sleep(1.5)
            else:
                print(f"Warning: Failed to query GDELT Doc API: {exc}", file=sys.stderr)
    return {}


_ARCHIVE_DOMAINS = {
    "wikipedia.org",
    "britannica.com",
    "wikimedia.org",
    "wiktionary.org",
    "dec.org.uk",
    "disasterphilanthropy.org",
    "andreabocellifoundation.org",
    "oxfam.org",
    "snopes.com",
}


def _deduplicate_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        url_clean = url.strip().rstrip("/")
        # Ignore social media redirects or empty
        if not url_clean or any(domain in url_clean for domain in ["twitter.com", "facebook.com", "t.co"]):
            continue
        # Skip archive, encyclopedia, and non-news domain lists
        parsed = urllib.parse.urlparse(url_clean)
        domain = parsed.netloc.lower()
        if any(arch in domain for arch in _ARCHIVE_DOMAINS):
            continue
        if url_clean not in seen:
            seen.add(url_clean)
            deduped.append(url)
    return deduped


def _merge_article_metadata(*maps: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for metadata_map in maps:
        for url, meta in metadata_map.items():
            current = merged.setdefault(url, {})
            for key, value in meta.items():
                if value or key not in current:
                    current[key] = value
    return merged


def _scrape_worker(
    url: str,
    meta: dict[str, str],
    sources: list[SourceProfile],
    timeout: int,
    extractor: str
) -> Article | tuple[str, Exception]:
    try:
        article = fetch_article_from_url(url, sources, timeout=timeout, extractor=extractor)
        if not article.image_url and meta.get("image_url"):
            article.image_url = meta["image_url"]
            article.metadata.setdefault("image_url", meta["image_url"])
        return article
    except Exception as exc:
        fallback_body = meta.get("description", "").strip()
        if len(fallback_body) >= 30:
            import hashlib
            from .sources import detect_source
            from .guardrails import extract_article_signals

            source_name = meta.get("source", "")
            hint = f"{source_name} {url} {meta.get('title', '')} {fallback_body}"
            source = detect_source(hint, sources)

            temp_meta = {
                "url": url,
                "title": meta.get("title", ""),
                "source": source_name,
                "image_url": meta.get("image_url", ""),
            }
            signals = extract_article_signals(meta.get("title", ""), fallback_body, temp_meta)
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

            fallback_article = Article(
                article_id=digest,
                path=url,
                source=source,
                title=meta.get("title", ""),
                body=f"[API Snippet Fallback] {fallback_body}",
                body_en=translate_to_english(fallback_body),
                image_url=meta.get("image_url", ""),
                metadata=temp_meta,
                signals=signals
            )
            return fallback_article
        else:
            return (url, exc)


def fetch_articles_from_apis(
    query: str,
    sources: list[SourceProfile],
    limit_per_api: int = 25,
    timeout: int = 20,
    extractor: str = "auto"
) -> tuple[list[Article], list[str]]:
    """Retrieve news articles from NewsAPI, GDELT, and Brave Search, then scrape their full text.

    Returns:
        tuple[list[Article], list[str]]: A list of successfully fetched Article objects
                                         and a list of warning/error messages.
    """
    print(f"Searching APIs for query: '{query}'...")
    news_map = _query_news_api(query, limit_per_api)
    brave_map = _query_brave_search(query, limit_per_api)
    gdelt_map = _query_gdelt(query, limit_per_api)

    # Merge results by source priority while preserving non-empty metadata such as images.
    merged_meta = _merge_article_metadata(gdelt_map, news_map, brave_map)

    all_urls = _deduplicate_urls(list(merged_meta.keys()))
    print(f"Found {len(all_urls)} unique article URL(s). Scraping content in parallel...")

    articles: list[Article] = []
    errors: list[str] = []

    max_workers = min(len(all_urls), 16) if all_urls else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_scrape_worker, url, merged_meta[url], sources, timeout, extractor)
            for url in all_urls
        ]

        for i, future in enumerate(futures, start=1):
            url = all_urls[i - 1]
            try:
                res = future.result()
                if isinstance(res, Article):
                    articles.append(res)
                    if "[API Snippet Fallback]" in res.body:
                        print(f"[{i}/{len(all_urls)}] Scraped: {url} -> Recovered using API snippet fallback.")
                    else:
                        print(f"[{i}/{len(all_urls)}] Scraped: {url} -> SUCCESS.")
                elif isinstance(res, tuple):
                    err_url, exc = res
                    err_msg = f"Failed to fetch {err_url}: {exc} (No valid snippet fallback)"
                    print(f"[{i}/{len(all_urls)}] Scraped: {url} -> FAILED: {exc}")
                    errors.append(err_msg)
            except Exception as exc:
                err_msg = f"Unexpected thread error fetching {url}: {exc}"
                print(f"[{i}/{len(all_urls)}] Scraped: {url} -> ERROR: {exc}")
                errors.append(err_msg)

    return articles, errors
