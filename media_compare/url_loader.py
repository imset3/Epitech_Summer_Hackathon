from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .guardrails import extract_article_signals
from .models import Article, SourceProfile
from .sources import detect_source

try:  # Optional dependency. Auto mode falls back to the internal parser if missing.
    from newspaper import Article as NewspaperArticle  # type: ignore
except Exception:  # pragma: no cover - depends on optional local installation
    NewspaperArticle = None  # type: ignore[assignment]

URL_RE = re.compile(r"https?://\S+", re.I)
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_BODY_CHARS = 24_000
_MIN_EXTRACTED_BODY_CHARS = 160
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


_NOISE_CUT_MARKERS = (
    " SECTIONS ",
    " TOP STORIES ",
    "ADVERTISEMENT",
    "RELATED STORIES",
    "MORE FROM",
    "READ MORE",
    "ALSO READ",
    "SIGN UP",
    "NEWSLETTER",
)
_NOISE_LINE_RE = re.compile(
    r"\b(SECTIONS|TOP STORIES|ADVERTISEMENT|RELATED STORIES|MORE FROM|READ MORE|ALSO READ|NEWSLETTER|"
    r"SUBSCRIBE|SIGN IN|LOG IN|COOKIES?|PRIVACY POLICY|TERMS OF USE|SHARE THIS ARTICLE)\b",
    re.I,
)
_SCHEMA_ARTICLE_TYPES = {"article", "newsarticle", "reportagenewsarticle", "blogposting"}


class ArticleFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExtractedArticle:
    title: str
    body: str
    metadata: dict[str, str]
    extractor: str


class _ArticleTextParser(HTMLParser):
    """Fallback HTML article extractor.

    The preferred extractor is newspaper3k. This parser remains as a dependency-light
    fallback for simple/static pages and tests. It now prefers text inside article/main
    containers before falling back to all visible paragraphs.
    """

    TEXT_TAGS = {"p", "h1", "h2", "h3", "li", "blockquote"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "form", "nav", "footer", "header", "aside"}
    CONTENT_TAGS = {"article", "main"}
    CONTENT_ATTR_RE = re.compile(r"\b(article|story|content|main|post|entry)\b", re.I)

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.article_text_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._tag_stack: list[str] = []
        self._content_stack: list[bool] = []
        self._content_depth = 0
        self._capture_title = False
        self._capture_text = False
        self._skip_depth = 0

    def _looks_like_content_container(self, tag: str, attr_map: dict[str, str]) -> bool:
        if tag in self.CONTENT_TAGS:
            return True
        role = attr_map.get("role", "")
        if role == "main":
            return True
        class_or_id = " ".join([attr_map.get("class", ""), attr_map.get("id", "")])
        return bool(self.CONTENT_ATTR_RE.search(class_or_id))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        attr_map = {key.lower(): (value or "") for key, value in attrs}

        is_content_container = False
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif self._looks_like_content_container(tag, attr_map):
            is_content_container = True
            self._content_depth += 1
        self._content_stack.append(is_content_container)

        if tag == "title":
            self._capture_title = True
            return

        if tag == "meta":
            key = (
                attr_map.get("property")
                or attr_map.get("name")
                or attr_map.get("itemprop")
                or ""
            ).strip().lower()
            content = attr_map.get("content", "").strip()
            if key and content:
                self.meta[key] = html.unescape(content)
            return

        if self._skip_depth == 0 and tag in self.TEXT_TAGS:
            self._capture_text = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        inside_content = self._content_depth > 0

        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._capture_title = False
        if tag in self.TEXT_TAGS:
            self._capture_text = False
            self.text_parts.append("\n")
            if inside_content:
                self.article_text_parts.append("\n")

        if self._content_stack:
            was_content_container = self._content_stack.pop()
            if was_content_container and self._content_depth > 0:
                self._content_depth -= 1
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = _clean_text(data)
        if not text:
            return
        if self._capture_title:
            self.title_parts.append(text)
        if self._capture_text:
            self.text_parts.append(text)
            if self._content_depth > 0:
                self.article_text_parts.append(text)


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value



def _cut_at_noise_marker(value: str) -> str:
    """Remove page furniture that newspaper/fallback extractors sometimes append.

    Some news sites expose the article text mixed with navigation blocks. In the
    AP sample, a valid headline was followed by "SECTIONS ... TOP STORIES ..." and
    then dozens of unrelated teasers. Cutting at these markers preserves the lead
    while preventing unrelated stories from reaching clustering, guardrails, or the LLM.
    """
    upper_value = f" {value.upper()} "
    cut_at: int | None = None
    for marker in _NOISE_CUT_MARKERS:
        idx = upper_value.find(marker)
        if idx >= 0:
            # upper_value has one leading space compared with value.
            source_idx = max(0, idx - 1)
            cut_at = source_idx if cut_at is None else min(cut_at, source_idx)
    if cut_at is not None:
        value = value[:cut_at]
    return value.strip()


def _is_noise_paragraph(paragraph: str) -> bool:
    clean = _clean_text(paragraph)
    if len(clean) < 35:
        return True
    if _NOISE_LINE_RE.search(clean):
        return True

    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]+", clean)
    if not words:
        return True

    # Menu/category blocks often have many short title-case tokens and little
    # punctuation. Real article paragraphs usually have sentence punctuation.
    titlecase_count = sum(1 for word in words if word[:1].isupper())
    punctuation_count = sum(clean.count(mark) for mark in ".!?;:")
    if len(words) >= 12 and titlecase_count / len(words) > 0.65 and punctuation_count <= 1:
        return True
    return False


def _paragraph_quality_score(paragraph: str) -> int:
    score = 0
    if re.search(r"\b(said|reported|according|official|officials|authorities|police|government|rescue|earthquake|quake|killed|injured|died|evacuated|magnitude)\b", paragraph, re.I):
        score += 2
    if re.search(r"[.!?]", paragraph):
        score += 1
    if len(paragraph) >= 120:
        score += 1
    return score


def _clean_article_body(value: str) -> str:
    """Normalize extracted article text and drop navigation/teaser pollution."""
    chunks: list[str] = []
    seen: set[str] = set()

    # Split on newlines first, then split any very long merged paragraph when a
    # noise marker appears mid-line.
    for raw_line in value.splitlines():
        paragraph = _clean_text(raw_line)
        if not paragraph:
            continue
        paragraph = _cut_at_noise_marker(paragraph)
        if not paragraph or _is_noise_paragraph(paragraph):
            continue
        key = paragraph.casefold()
        if key in seen:
            continue
        seen.add(key)
        chunks.append(paragraph)

    # If the extractor returned a single long mixed blob, keep the best first
    # sentences and avoid later unrelated teasers.
    if len(chunks) <= 1 and value:
        blob = _cut_at_noise_marker(_clean_text(value))
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", blob) if s.strip()]
        rebuilt: list[str] = []
        for sentence in sentences:
            if _is_noise_paragraph(sentence):
                continue
            rebuilt.append(sentence)
            if len(rebuilt) >= 12:
                break
        if rebuilt:
            chunks = [" ".join(rebuilt)]

    return "\n".join(chunks)[:_MAX_BODY_CHARS]


def _noise_score(value: str) -> int:
    return len(_NOISE_LINE_RE.findall(value)) + sum(value.upper().count(marker.strip()) for marker in _NOISE_CUT_MARKERS)


def _normalize_body_text(value: str) -> str:
    return _clean_article_body(value)


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    slug = Path(parsed.path.rstrip("/")).name or parsed.netloc
    return urllib.parse.unquote(slug).replace("-", " ").replace("_", " ").strip().title()


def _extract_url(line: str) -> str | None:
    match = URL_RE.search(line.strip())
    if not match:
        return None
    return match.group(0).rstrip(").,;]")


def read_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        url = _extract_url(line)
        if url:
            urls.append(url)
    return urls


def _domain_hint(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower().removeprefix("www.")
    return f"{netloc} {url}"


def _fetch_url(url: str, timeout: int) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,fr;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        raise ArticleFetchError(f"HTTP {exc.code} while fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise ArticleFetchError(f"Could not fetch {url}: {exc.reason}") from exc

    charset = "utf-8"
    match = re.search(r"charset=([^;]+)", content_type, re.I)
    if match:
        charset = match.group(1).strip()
    return raw.decode(charset, errors="replace"), content_type


def _best_title(parser: _ArticleTextParser, url: str) -> str:
    meta = parser.meta
    candidates = [
        meta.get("og:title", ""),
        meta.get("twitter:title", ""),
        meta.get("headline", ""),
        " ".join(parser.title_parts),
        _title_from_url(url),
    ]
    for candidate in candidates:
        clean = _clean_text(candidate)
        if clean:
            return clean[:180]
    return _title_from_url(url)


def _metadata_from_parser(parser: _ArticleTextParser, url: str) -> dict[str, str]:
    meta = parser.meta
    metadata: dict[str, str] = {"url": url}

    title = meta.get("og:title") or meta.get("twitter:title") or meta.get("headline")
    if title:
        metadata["title"] = _clean_text(title)

    canonical = meta.get("og:url") or meta.get("twitter:url")
    if canonical:
        metadata["canonical_url"] = _clean_text(canonical)

    date = (
        meta.get("article:published_time")
        or meta.get("article:modified_time")
        or meta.get("date")
        or meta.get("dc.date")
        or meta.get("dc.date.issued")
        or meta.get("pubdate")
        or meta.get("publishdate")
        or meta.get("datepublished")
        or meta.get("datecreated")
    )
    if date:
        metadata["publication_date"] = _clean_text(date)

    author = meta.get("author") or meta.get("article:author")
    if author:
        metadata["author"] = _clean_text(author)

    site = meta.get("og:site_name") or urllib.parse.urlparse(url).netloc
    if site:
        metadata["source"] = _clean_text(site)

    return metadata


def _body_from_parts(parts: list[str]) -> str:
    current: list[str] = []
    lines: list[str] = []

    for part in parts:
        if part == "\n":
            if current:
                lines.append(" ".join(current))
                current = []
            continue
        current.append(part)

    if current:
        lines.append(" ".join(current))

    return _clean_article_body("\n".join(lines))


def _body_from_parser(parser: _ArticleTextParser) -> str:
    article_body = _body_from_parts(parser.article_text_parts)
    if len(article_body) >= _MIN_EXTRACTED_BODY_CHARS:
        return article_body
    return _body_from_parts(parser.text_parts)


def _metadata_from_newspaper(article: Any, base_metadata: dict[str, str]) -> dict[str, str]:
    metadata = dict(base_metadata)
    metadata["extractor"] = "newspaper3k"

    title = _clean_text(str(getattr(article, "title", "") or ""))
    if title:
        metadata["title"] = title

    publish_date = getattr(article, "publish_date", None)
    if publish_date:
        try:
            metadata["publication_date"] = publish_date.isoformat()
        except AttributeError:
            metadata["publication_date"] = _clean_text(str(publish_date))

    authors = getattr(article, "authors", None) or []
    if authors:
        metadata["author"] = _clean_text(", ".join(str(author) for author in authors))

    meta_site_name = _clean_text(str(getattr(article, "meta_site_name", "") or ""))
    if meta_site_name:
        metadata["source"] = meta_site_name

    canonical_link = _clean_text(str(getattr(article, "canonical_link", "") or ""))
    if canonical_link:
        metadata["canonical_url"] = canonical_link

    return metadata




def _iter_json_ld_items(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for entry in graph:
                items.extend(_iter_json_ld_items(entry))
        items.append(value)
    elif isinstance(value, list):
        for entry in value:
            items.extend(_iter_json_ld_items(entry))
    return items


def _json_ld_type_matches(item: dict[str, Any]) -> bool:
    raw_type = item.get("@type") or item.get("type")
    if isinstance(raw_type, str):
        types = [raw_type]
    elif isinstance(raw_type, list):
        types = [str(value) for value in raw_type]
    else:
        types = []
    return any(value.casefold() in _SCHEMA_ARTICLE_TYPES for value in types)


def _string_or_empty(value: Any) -> str:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, dict):
        for key in ("name", "headline", "text"):
            if isinstance(value.get(key), str):
                return _clean_text(value[key])
    return ""


def _extract_json_ld_blocks(raw_html: str) -> list[str]:
    return re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw_html,
        flags=re.I | re.S,
    )


def _extract_with_json_ld(url: str, raw_html: str, parser_metadata: dict[str, str]) -> ExtractedArticle:
    best_item: dict[str, Any] | None = None
    best_body = ""

    for block in _extract_json_ld_blocks(raw_html):
        block = html.unescape(block).strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in _iter_json_ld_items(data):
            if not _json_ld_type_matches(item):
                continue
            body_candidates = [
                item.get("articleBody"),
                item.get("text"),
                item.get("description"),
            ]
            for candidate in body_candidates:
                body = _clean_article_body(_string_or_empty(candidate))
                if len(body) > len(best_body):
                    best_body = body
                    best_item = item

    if best_item is None or len(best_body) < _MIN_EXTRACTED_BODY_CHARS:
        raise ArticleFetchError("JSON-LD did not contain enough article body text")

    metadata = dict(parser_metadata)
    metadata["extractor"] = "json-ld"

    title = (
        _string_or_empty(best_item.get("headline"))
        or _string_or_empty(best_item.get("name"))
        or parser_metadata.get("title")
        or _title_from_url(url)
    )
    metadata["title"] = title

    date_published = _string_or_empty(best_item.get("datePublished"))
    date_modified = _string_or_empty(best_item.get("dateModified"))
    if date_published:
        metadata["publication_date"] = date_published
    elif date_modified:
        metadata["publication_date"] = date_modified

    author = best_item.get("author")
    if isinstance(author, list):
        authors = [_string_or_empty(item) for item in author]
        authors = [item for item in authors if item]
        if authors:
            metadata["author"] = ", ".join(authors)
    else:
        author_name = _string_or_empty(author)
        if author_name:
            metadata["author"] = author_name

    publisher = best_item.get("publisher")
    publisher_name = _string_or_empty(publisher)
    if publisher_name:
        metadata["source"] = publisher_name

    return ExtractedArticle(title=title[:180], body=best_body, metadata=metadata, extractor="json-ld")


def _body_quality_too_low(body: str) -> bool:
    if len(body) < _MIN_EXTRACTED_BODY_CHARS:
        return True
    if _noise_score(body) >= 2:
        return True
    paragraphs = [p for p in body.splitlines() if p.strip()]
    if not paragraphs:
        return True
    quality = sum(_paragraph_quality_score(p) for p in paragraphs[:8])
    return quality <= 1

def _extract_with_newspaper(url: str, raw_html: str, parser_metadata: dict[str, str]) -> ExtractedArticle:
    if NewspaperArticle is None:
        raise ArticleFetchError("newspaper3k is not installed")

    article = NewspaperArticle(url=url)
    article.set_html(raw_html)
    article.parse()

    raw_body = str(getattr(article, "text", "") or "")
    body = _normalize_body_text(raw_body)
    if _body_quality_too_low(body):
        raise ArticleFetchError("newspaper3k extracted low-quality or polluted article text")

    metadata = _metadata_from_newspaper(article, parser_metadata)
    title = metadata.get("title") or _title_from_url(url)
    return ExtractedArticle(title=title[:180], body=body, metadata=metadata, extractor="newspaper3k")


def _extract_with_fallback_parser(url: str, parser: _ArticleTextParser, parser_metadata: dict[str, str]) -> ExtractedArticle:
    metadata = dict(parser_metadata)
    metadata["extractor"] = "fallback-html-parser"
    title = metadata.get("title") or _best_title(parser, url)
    body = _body_from_parser(parser)

    if _body_quality_too_low(body):
        raise ArticleFetchError(
            f"Could not extract clean article text from {url}. The page may be paywalled, blocked, JavaScript-rendered, or too polluted with page furniture."
        )

    return ExtractedArticle(title=title[:180], body=body, metadata=metadata, extractor="fallback-html-parser")


def _extract_article(url: str, raw_html: str, extractor: str = "auto") -> ExtractedArticle:
    if extractor not in {"auto", "newspaper", "fallback"}:
        raise ArticleFetchError(f"Unknown extractor '{extractor}'. Use auto, newspaper, or fallback.")

    parser = _ArticleTextParser()
    parser.feed(raw_html)
    parser_metadata = _metadata_from_parser(parser, url)

    extractor_errors: list[str] = []

    if extractor == "auto":
        try:
            return _extract_with_json_ld(url, raw_html, parser_metadata)
        except Exception as exc:
            extractor_errors.append(f"json-ld: {exc}")

    newspaper_error = ""
    if extractor in {"auto", "newspaper"}:
        try:
            return _extract_with_newspaper(url, raw_html, parser_metadata)
        except Exception as exc:
            newspaper_error = str(exc)
            extractor_errors.append(f"newspaper3k: {newspaper_error}")
            if extractor == "newspaper":
                raise ArticleFetchError(f"newspaper3k extraction failed for {url}: {newspaper_error}") from exc

    try:
        extracted = _extract_with_fallback_parser(url, parser, parser_metadata)
    except Exception as exc:
        if extractor_errors:
            raise ArticleFetchError(f"All extractors failed for {url}: {' | '.join([*extractor_errors, f'fallback: {exc}'])}") from exc
        raise
    if extractor_errors:
        extracted.metadata["extractor_fallback_reason"] = " | ".join(extractor_errors)
    return extracted


def fetch_article_from_url(
    url: str,
    sources: list[SourceProfile],
    timeout: int = 20,
    extractor: str = "auto",
) -> Article:
    raw_html, content_type = _fetch_url(url, timeout=timeout)
    if "html" not in content_type.lower() and "xml" not in content_type.lower() and "" != content_type:
        raise ArticleFetchError(f"Unsupported content type for {url}: {content_type}")

    extracted = _extract_article(url, raw_html, extractor=extractor)
    hint = " ".join([
        extracted.metadata.get("source", ""),
        _domain_hint(url),
        extracted.title,
        extracted.body[:500],
    ])
    source = detect_source(hint, sources)
    signals = extract_article_signals(extracted.title, extracted.body, extracted.metadata)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]

    return Article(
        article_id=digest,
        path=url,
        source=source,
        title=extracted.title,
        body=extracted.body,
        metadata=extracted.metadata,
        signals=signals,
    )


def load_articles_from_url_file(
    path: Path,
    sources: list[SourceProfile],
    timeout: int = 20,
    extractor: str = "auto",
) -> tuple[list[Article], list[str]]:
    articles: list[Article] = []
    errors: list[str] = []
    for url in read_url_list(path):
        try:
            articles.append(fetch_article_from_url(url, sources, timeout=timeout, extractor=extractor))
        except ArticleFetchError as exc:
            errors.append(str(exc))
    return articles, errors
