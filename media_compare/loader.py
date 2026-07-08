from __future__ import annotations

import hashlib
from pathlib import Path

from .guardrails import extract_article_signals
from .models import Article, SourceProfile
from .sources import detect_source

SUPPORTED_EXTENSIONS = {".txt"}
SUPPORTED_METADATA_KEYS = {
    "source",
    "source_id",
    "title",
    "date",
    "publication_date",
    "language",
    "url",
    "author",
    "event_date",
    "published",
    "datetime",
    "time",
    "location",
    "place",
    "city",
    "country",
    "region",
}


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Parse simple metadata lines at the top of a text file.

    Supported lines:
        SOURCE: Le Monde
        SOURCE_ID: lemonde
        TITLE: Example title
        DATE: 2026-07-08
        PUBLICATION_DATE: 2026-07-08
        LANGUAGE: English

    Parsing stops at the first blank line or non key/value line.
    """
    metadata: dict[str, str] = {}
    lines = raw.splitlines()
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            break
        if ":" not in stripped:
            body_start = i
            break
        key, value = stripped.split(":", 1)
        key = key.strip().lower()
        if key not in SUPPORTED_METADATA_KEYS:
            body_start = i
            break
        metadata[key] = value.strip()
    else:
        body_start = len(lines)

    body = "\n".join(lines[body_start:]).strip()
    return metadata, body or raw.strip()


def _fallback_title(path: Path, body: str) -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if 8 <= len(first_line) <= 140:
        return first_line
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def load_articles(folder: Path, sources: list[SourceProfile]) -> list[Article]:
    files = sorted(
        path for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    articles: list[Article] = []
    for path in files:
        raw = path.read_text(encoding="utf-8", errors="replace")
        metadata, body = _parse_front_matter(raw)

        hint = " ".join([
            metadata.get("source", ""),
            path.name,
            "\n".join(raw.splitlines()[:8]),
        ])
        source = detect_source(hint, sources)
        title = metadata.get("title") or _fallback_title(path, body)
        signals = extract_article_signals(title, body, metadata)

        digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:10]
        articles.append(
            Article(
                article_id=digest,
                path=str(path),
                source=source,
                title=title,
                body=body,
                metadata=metadata,
                signals=signals,
            )
        )
    return articles
