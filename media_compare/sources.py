from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from .models import SourceProfile


DEFAULT_UNKNOWN = SourceProfile(
    name="Independent / Unknown",
    aliases=["independent", "unknown", "blog", "local"],
    trust=0.50,
    reach=0.30,
    notes="Default when no known source is detected.",
)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.casefold().strip()


def load_sources(config_path: Path) -> list[SourceProfile]:
    if not config_path.exists():
        return [DEFAULT_UNKNOWN]

    data = json.loads(config_path.read_text(encoding="utf-8"))
    sources: list[SourceProfile] = []
    for item in data.get("sources", []):
        sources.append(
            SourceProfile(
                name=item["name"],
                aliases=item.get("aliases", []),
                trust=float(item.get("trust", 0.5)),
                reach=float(item.get("reach", 0.3)),
                notes=item.get("notes", ""),
            )
        )
    return sources or [DEFAULT_UNKNOWN]


def detect_source(text_hint: str, sources: list[SourceProfile]) -> SourceProfile:
    hint = normalize(text_hint.replace("_", " ").replace("-", " "))
    for source in sources:
        candidates = [source.name, *source.aliases]
        if any(normalize(candidate) in hint for candidate in candidates):
            return source
    return next((s for s in sources if s.name == DEFAULT_UNKNOWN.name), DEFAULT_UNKNOWN)
