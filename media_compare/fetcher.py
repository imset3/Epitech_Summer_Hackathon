from __future__ import annotations

import json
import os
import re
import sys
import time
import html
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .models import Article, SourceProfile
from .url_loader import fetch_article_from_url, ArticleFetchError
from .translator import translate_to_english


NEWSAPI_CACHE_TTL_SECONDS = 10 * 60
NEWSAPI_RATE_LIMIT_COOLDOWN_SECONDS = 15 * 60
_NEWSAPI_CACHE: dict[tuple[str, int, int], tuple[float, dict[str, dict[str, str]]]] = {}
_NEWSAPI_RATE_LIMITED_UNTIL = 0.0


def _candidate_queries(query: str, max_variants: int = 5) -> list[str]:
    base = " ".join(query.split())
    if not base:
        return []

    variants = [base]
    word_count = len(base.split())
    if 1 < word_count <= 7:
        variants.append(f'"{base}"')
    variants.extend([
        f"{base} news",
        f"{base} latest",
        f"{base} report",
        f"{base} analysis",
    ])

    seen: set[str] = set()
    deduped: list[str] = []
    for variant in variants:
        key = variant.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(variant)
        if len(deduped) >= max(1, max_variants):
            break
    return deduped


def _newsapi_candidate_queries(candidate_queries: list[str]) -> list[str]:
    """Use NewsAPI sparingly: original query plus exact phrase when available."""
    selected: list[str] = []
    for candidate in candidate_queries:
        if not selected:
            selected.append(candidate)
        elif candidate.startswith('"') and candidate.endswith('"'):
            selected.append(candidate)
        if len(selected) >= 2:
            break
    return selected


def _query_news_api(query: str, limit: int, pages: int = 1) -> dict[str, dict[str, str]]:
    global _NEWSAPI_RATE_LIMITED_UNTIL

    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        print("Warning: NEWS_API_KEY not set. Skipping NewsAPI.", file=sys.stderr)
        return {}

    now = time.time()
    if now < _NEWSAPI_RATE_LIMITED_UNTIL:
        remaining = int(_NEWSAPI_RATE_LIMITED_UNTIL - now)
        print(f"NewsAPI is temporarily rate-limited; skipping for {remaining}s and using other sources.", file=sys.stderr)
        return {}

    cache_key = (query.casefold(), max(1, min(limit, 100)), max(1, pages))
    cached = _NEWSAPI_CACHE.get(cache_key)
    if cached and now - cached[0] < NEWSAPI_CACHE_TTL_SECONDS:
        return dict(cached[1])

    results: dict[str, dict[str, str]] = {}
    page_size = max(1, min(limit, 100))
    encoded_query = urllib.parse.quote(query)
    for page in range(1, max(1, pages) + 1):
        url = f"https://newsapi.org/v2/everything?q={encoded_query}&pageSize={page_size}&page={page}&sortBy=publishedAt&apiKey={api_key}"
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
                    break
            for art in data.get("articles", []):
                article_url = art.get("url")
                if article_url:
                    results[article_url] = {
                        "title": art.get("title", "") or "",
                        "description": art.get("description", "") or art.get("content", "") or "",
                        "source": art.get("source", {}).get("name", "Unknown") or "Unknown",
                        "image_url": art.get("urlToImage", "") or "",
                        "published_at": art.get("publishedAt", "") or "",
                        "search_query": query,
                        "discovery_api": "newsapi",
                    }
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _NEWSAPI_RATE_LIMITED_UNTIL = time.time() + NEWSAPI_RATE_LIMIT_COOLDOWN_SECONDS
                print(
                    f"Warning: NewsAPI rate limit reached while querying '{query}'. "
                    "Continuing with Google News RSS, Brave, and GDELT.",
                    file=sys.stderr,
                )
            else:
                print(f"Warning: Failed to query NewsAPI page {page} for '{query}': {exc}", file=sys.stderr)
            break
        except Exception as exc:
            print(f"Warning: Failed to query NewsAPI page {page} for '{query}': {exc}", file=sys.stderr)
            break
    _NEWSAPI_CACHE[cache_key] = (time.time(), dict(results))
    return results


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
                    thumbnail = res.get("thumbnail") or {}
                    image_url = thumbnail.get("src", "") if isinstance(thumbnail, dict) else str(thumbnail or "")
                    results[article_url] = {
                        "title": res.get("title", "") or "",
                        "description": res.get("description", "") or "",
                        "source": res.get("page_fields", {}).get("source", "") or urllib.parse.urlparse(article_url).netloc,
                        "image_url": image_url,
                        "search_query": query,
                        "discovery_api": "brave",
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
                            "published_at": art.get("seendate", "") or "",
                            "search_query": query,
                            "discovery_api": "gdelt",
                        }
                return results
        except Exception as exc:
            if attempt == 0:
                # Wait 1.5 seconds and retry once
                time.sleep(1.5)
            else:
                print(f"Warning: Failed to query GDELT Doc API: {exc}", file=sys.stderr)
    return {}


def _query_google_news_rss(query: str, limit: int) -> dict[str, dict[str, str]]:
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    request = urllib.request.Request(
        rss_url,
        headers={"User-Agent": "media-compare-fetcher"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            root = ET.fromstring(response.read())
    except Exception as exc:
        print(f"Warning: Failed to query Google News RSS for '{query}': {exc}", file=sys.stderr)
        return {}

    results: dict[str, dict[str, str]] = {}
    for item in root.findall(".//item")[:limit]:
        link = item.findtext("link") or ""
        title = item.findtext("title") or ""
        description = item.findtext("description") or ""
        pub_date = item.findtext("pubDate") or ""
        source_el = item.find("source")
        source_name = source_el.text if source_el is not None and source_el.text else ""
        if source_name and title.endswith(f" - {source_name}"):
            title = title[: -len(f" - {source_name}")].strip()
        if not link or not title:
            continue
        results[link] = {
            "title": html.unescape(title),
            "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description))).strip(),
            "source": source_name or urllib.parse.urlparse(link).netloc,
            "image_url": "",
            "published_at": pub_date,
            "search_query": query,
            "discovery_api": "google-news-rss",
        }
    return results


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


_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src"}


def _canonical_url_key(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    query_items = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower in _TRACKING_QUERY_KEYS or any(key_lower.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))
    query = urllib.parse.urlencode(sorted(query_items))
    return urllib.parse.urlunparse((scheme, netloc, path, "", query, ""))


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
        key = _canonical_url_key(url_clean)
        if key not in seen:
            seen.add(key)
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
    extractor: str,
    config_path: Path | None,
    llm_provider: str | None,
    llm_model: str | None,
    local_base_url: str | None,
) -> Article | tuple[str, Exception]:
    try:
        article = fetch_article_from_url(
            url,
            sources,
            timeout=timeout,
            extractor=extractor,
            config_path=config_path,
            llm_provider=llm_provider,
            llm_model=llm_model,
            local_base_url=local_base_url,
        )
        if not article.image_url and meta.get("image_url"):
            article.image_url = meta["image_url"]
            article.metadata.setdefault("image_url", meta["image_url"])
        if meta.get("published_at"):
            published_date = meta["published_at"].split("T")[0] if "T" in meta["published_at"] else meta["published_at"]
            article.metadata.setdefault("date", published_date)
            article.metadata.setdefault("publication_date", meta["published_at"])
        if meta.get("discovery_api"):
            article.metadata.setdefault("discovery_api", meta["discovery_api"])
        if meta.get("search_query"):
            article.metadata.setdefault("search_query", meta["search_query"])
        return article
    except Exception as exc:
        fallback_body = meta.get("description", "").strip()
        if len(fallback_body) >= 30:
            import hashlib
            from .sources import detect_source
            from .guardrails import extract_article_signals

            source_name = meta.get("source", "")
            hint = f"{source_name} {url} {meta.get('title', '')} {fallback_body}"
            source = detect_source(
                hint,
                sources,
                config_path=config_path,
                llm_provider=llm_provider,
                llm_model=llm_model,
                local_base_url=local_base_url,
            )

            temp_meta = {
                "url": url,
                "title": meta.get("title", ""),
                "source": source_name,
                "image_url": meta.get("image_url", ""),
                "date": meta.get("published_at", "").split("T")[0] if "T" in meta.get("published_at", "") else meta.get("published_at", ""),
                "publication_date": meta.get("published_at", ""),
                "discovery_api": meta.get("discovery_api", ""),
                "search_query": meta.get("search_query", ""),
            }
            signals = extract_article_signals(meta.get("title", ""), fallback_body, temp_meta)
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

            fallback_article = Article(
                article_id=digest,
                path=url,
                source=source,
                title=meta.get("title", ""),
                body=f"[API Snippet Fallback] {fallback_body}",
                body_en=translate_to_english(
                    fallback_body,
                    provider=llm_provider,
                    model=llm_model,
                    local_base_url=local_base_url,
                ) if llm_provider in ("local", "dry-run", None) else fallback_body,
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
    extractor: str = "auto",
    config_path: Path | None = None,
    query_variants: int = 5,
    max_articles: int = 60,
    discovery_workers: int = 12,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    local_base_url: str | None = None,
) -> tuple[list[Article], list[str]]:
    """Retrieve news articles from NewsAPI, GDELT, and Brave Search, then scrape their full text.

    Returns:
        tuple[list[Article], list[str]]: A list of successfully fetched Article objects
                                         and a list of warning/error messages.
    """
    candidate_queries = _candidate_queries(query, max_variants=query_variants)
    print(f"Searching APIs for query: '{query}' with {len(candidate_queries)} query variant(s)...")

    discovery_maps: dict[str, list[dict[str, dict[str, str]]]] = {
        "rss": [],
        "gdelt": [],
        "newsapi": [],
        "brave": [],
    }
    discovery_warnings: list[str] = []

    per_query_limit = max(1, limit_per_api)
    discovery_tasks: list[tuple[str, str, Any, tuple[Any, ...]]] = []
    newsapi_queries = _newsapi_candidate_queries(candidate_queries)
    for candidate_query in newsapi_queries:
        newsapi_results = _query_news_api(candidate_query, per_query_limit, pages=1)
        if newsapi_results:
            discovery_maps["newsapi"].append(newsapi_results)
        if time.time() < _NEWSAPI_RATE_LIMITED_UNTIL:
            break

    for i, candidate_query in enumerate(candidate_queries):
        # RSS and Brave query all variants to maximize diversity. NewsAPI is
        # intentionally queried above in a smaller, sequential budget so free
        # tiers do not hit 429 as easily.
        discovery_tasks.extend([
            ("rss",     candidate_query, _query_google_news_rss, (candidate_query, per_query_limit)),
            ("brave",   candidate_query, _query_brave_search,    (candidate_query, per_query_limit)),
        ])
        # GDELT: only query once with the base query (strict rate limits → 429 on repeated calls)
        if i == 0:
            discovery_tasks.append(
                ("gdelt", candidate_query, _query_gdelt, (candidate_query, per_query_limit))
            )

    with ThreadPoolExecutor(max_workers=min(len(discovery_tasks), max(1, discovery_workers))) as executor:
        futures = {
            executor.submit(fn, *args): (source_name, candidate_query)
            for source_name, candidate_query, fn, args in discovery_tasks
        }
        for future in as_completed(futures):
            source_name, candidate_query = futures[future]
            try:
                discovery_maps[source_name].append(future.result())
            except Exception as exc:
                warning = f"{source_name} discovery failed for '{candidate_query}': {exc}"
                print(f"Warning: {warning}", file=sys.stderr)
                discovery_warnings.append(warning)

    # Merge results by source priority while preserving non-empty metadata such as images.
    merged_meta = _merge_article_metadata(
        *discovery_maps["rss"],
        *discovery_maps["gdelt"],
        *discovery_maps["newsapi"],
        *discovery_maps["brave"],
    )

    all_urls = _deduplicate_urls(list(merged_meta.keys()))[:max(1, max_articles)]
    print(f"Found {len(all_urls)} unique article URL(s). Scraping content in parallel...")

    articles: list[Article] = []
    errors: list[str] = [*discovery_warnings]

    max_workers = min(len(all_urls), 16) if all_urls else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _scrape_worker,
                url,
                merged_meta[url],
                sources,
                timeout,
                extractor,
                config_path,
                llm_provider,
                llm_model,
                local_base_url,
            ): url
            for url in all_urls
        }

        for i, future in enumerate(as_completed(futures), start=1):
            url = futures[future]
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
