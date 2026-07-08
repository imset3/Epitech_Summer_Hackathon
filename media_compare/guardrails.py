from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from .models import Article, ArticleSignals, StoryCluster

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}

WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
}

LOCATION_STOPWORDS = WEEKDAYS | {
    "government", "ministers", "opposition", "authorities", "officials", "experts",
    "emergency", "services", "article", "report", "reports", "source", "sources",
    "centre", "center", "agency", "ministry", "office", "committee",
    "the", "a", "an", "new", "current", "latest", "today", "yesterday", "tomorrow",
}

LOCATION_METADATA_KEYS = ("location", "place", "city", "country", "region")
DATE_METADATA_KEYS = ("event_date", "date", "publication_date", "published", "datetime", "time")

ISO_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b")
DMY_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre)"
    r"\s+(20\d{2}|19\d{2})\b",
    re.I,
)
MDY_RE = re.compile(
    r"\b"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(20\d{2}|19\d{2})\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")

# Intentionally simple. For production, replace this with spaCy/Stanza NER.
LOCATION_RE = re.compile(
    r"\b(?:near|outside|around|in|at|from|across|over|within|throughout|inside)\s+"
    r"(?:the\s+)?"
    r"([A-ZÀ-Þ][\wÀ-ÿ'’-]+(?:\s+(?:and|of|de|du|des|la|le|the|&)?\s*"
    r"[A-ZÀ-Þ][\wÀ-ÿ'’-]+){0,3})"
)


@dataclass(frozen=True)
class MergeGuardrail:
    allow: bool
    bonus: float = 0.0
    warning: str = ""


def _strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _normalize_location(value: str) -> str:
    clean = re.sub(r"[^\wÀ-ÿ'’ -]", " ", value).strip()
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"^(the|la|le|les|l')\s+", "", clean, flags=re.I)
    clean = _strip_accents(clean).casefold()
    return clean


def _display_location(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,:;()[]{}\n\t"))


def _is_probable_location(value: str) -> bool:
    normalized = _normalize_location(value)
    if not normalized or normalized in LOCATION_STOPWORDS:
        return False
    parts = normalized.split()
    if any(part in WEEKDAYS for part in parts):
        return False
    if any(part in MONTHS for part in parts):
        return False
    if any(part in LOCATION_STOPWORDS for part in parts):
        return False
    if len(normalized) < 3:
        return False
    return True


def _parse_date_value(value: str) -> date | None:
    value = value.strip()
    iso = ISO_DATE_RE.search(value)
    if iso:
        year, month, day = map(int, iso.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    dmy = DMY_RE.search(value)
    if dmy:
        day_raw, month_raw, year_raw = dmy.groups()
        month = MONTHS.get(_strip_accents(month_raw).casefold())
        if month:
            try:
                return date(int(year_raw), month, int(day_raw))
            except ValueError:
                return None

    mdy = MDY_RE.search(value)
    if mdy:
        month_raw, day_raw, year_raw = mdy.groups()
        month = MONTHS.get(month_raw.casefold())
        if month:
            try:
                return date(int(year_raw), month, int(day_raw))
            except ValueError:
                return None

    return None


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_article_signals(title: str, body: str, metadata: dict[str, str]) -> ArticleSignals:
    dates: list[str] = []
    years: list[str] = []
    locations: list[str] = []

    for key in DATE_METADATA_KEYS:
        raw = metadata.get(key)
        if not raw:
            continue
        parsed = _parse_date_value(raw)
        if parsed:
            dates.append(parsed.isoformat())

    combined_text = f"{title}\n{body}"

    # Primary date guardrails should prefer article metadata. Body dates are often
    # background references such as "11 June" or "21 June" inside a 7 July story.
    # Only fall back to body dates when metadata gives no usable date.
    if not dates:
        for regex in (ISO_DATE_RE, DMY_RE, MDY_RE):
            for match in regex.finditer(combined_text):
                parsed = _parse_date_value(match.group(0))
                if parsed:
                    dates.append(parsed.isoformat())

    for year_match in YEAR_RE.finditer(combined_text):
        years.append(year_match.group(1))

    for key in LOCATION_METADATA_KEYS:
        raw = metadata.get(key)
        if raw and _is_probable_location(raw):
            locations.append(_display_location(raw))

    for line in combined_text.splitlines():
        for match in LOCATION_RE.finditer(line):
            candidate = _display_location(match.group(1))
            # Avoid swallowing a following phrase that starts with a capitalized word.
            candidate = re.split(r"\b(?:said|reported|claimed|explained|warned)\b", candidate, flags=re.I)[0].strip()
            if _is_probable_location(candidate):
                locations.append(candidate)

    return ArticleSignals(
        dates=_unique_preserve_order(dates),
        years=_unique_preserve_order(years),
        locations=_unique_preserve_order(locations),
    )


def _dates(article: Article) -> set[date]:
    parsed: set[date] = set()
    for raw in article.signals.dates:
        try:
            parsed.add(date.fromisoformat(raw))
        except ValueError:
            continue
    return parsed


def _years(article: Article) -> set[str]:
    return set(article.signals.years)


def _locations(article: Article) -> set[str]:
    return {_normalize_location(item) for item in article.signals.locations if _is_probable_location(item)}


def _cluster_dates(cluster: list[Article]) -> set[date]:
    result: set[date] = set()
    for article in cluster:
        result |= _dates(article)
    return result


def _cluster_years(cluster: list[Article]) -> set[str]:
    result: set[str] = set()
    for article in cluster:
        result |= _years(article)
    return result


def _cluster_locations(cluster: list[Article]) -> set[str]:
    result: set[str] = set()
    for article in cluster:
        result |= _locations(article)
    return result


def _min_date_gap_days(a: set[date], b: set[date]) -> int | None:
    if not a or not b:
        return None
    return min(abs((left - right).days) for left in a for right in b)


def check_merge_guardrail(
    article: Article,
    cluster: list[Article],
    *,
    max_date_gap_days: int = 21,
) -> MergeGuardrail:
    """Return whether date/location evidence allows adding article to cluster.

    The guardrail is deliberately conservative: it blocks obvious same-day/different-place
    and far-apart-date matches, but it does not force a merge by itself.
    """
    article_dates = _dates(article)
    cluster_dates = _cluster_dates(cluster)
    article_years = _years(article)
    cluster_years = _cluster_years(cluster)
    article_locations = _locations(article)
    cluster_locations = _cluster_locations(cluster)

    date_gap = _min_date_gap_days(article_dates, cluster_dates)
    date_overlap = bool(article_dates and cluster_dates and article_dates & cluster_dates)
    date_close = date_gap is not None and date_gap <= max_date_gap_days
    location_overlap = bool(article_locations and cluster_locations and article_locations & cluster_locations)
    location_conflict = bool(article_locations and cluster_locations and not location_overlap)

    if date_gap is not None and date_gap > max_date_gap_days:
        return MergeGuardrail(
            allow=False,
            warning=(
                f"Blocked merge: date signals are {date_gap} days apart "
                f"(max {max_date_gap_days})."
            ),
        )

    if not article_dates and not cluster_dates and article_years and cluster_years and not (article_years & cluster_years):
        return MergeGuardrail(
            allow=False,
            warning="Blocked merge: year signals do not overlap.",
        )

    if (date_overlap or date_close) and location_conflict:
        return MergeGuardrail(
            allow=False,
            warning="Blocked merge: date signals match or are close, but location signals differ.",
        )

    bonus = 0.0
    if date_overlap:
        bonus += 0.025
    elif date_close:
        bonus += 0.010
    if location_overlap:
        bonus += 0.030
    if (date_overlap or date_close) and location_overlap:
        bonus += 0.020

    warning = ""
    if location_conflict and not (date_overlap or date_close):
        warning = "Location signals differ, but dates were not close enough to block the merge."

    return MergeGuardrail(allow=True, bonus=round(bonus, 4), warning=warning)


def cluster_signal_summary(articles: list[Article]) -> tuple[list[str], list[str]]:
    date_values: list[str] = []
    location_values: list[str] = []
    seen_locations: set[str] = set()

    for article in articles:
        date_values.extend(article.signals.dates)
        for location in article.signals.locations:
            key = _normalize_location(location)
            if key not in seen_locations:
                seen_locations.add(key)
                location_values.append(location)

    return _unique_preserve_order(date_values), location_values


def cluster_guardrail_notes(cluster: StoryCluster) -> tuple[list[str], float]:
    dates, locations = cluster_signal_summary(cluster.articles)
    notes: list[str] = []
    score = 0.70

    if dates:
        parsed_dates = sorted({date.fromisoformat(item) for item in dates})
        if len(parsed_dates) == 1:
            notes.append(f"Date guardrail: shared primary date signal {parsed_dates[0].isoformat()}.")
            score += 0.15
        else:
            span = (parsed_dates[-1] - parsed_dates[0]).days
            if span <= 21:
                notes.append(f"Date guardrail: primary date signals are close together over {span} day(s).")
                score += 0.05
            else:
                notes.append(f"Date guardrail warning: primary date signals span {span} day(s); timing may describe different phases or events.")
                score -= 0.25
    else:
        notes.append("Date guardrail: no usable exact primary date signal found.")
        score -= 0.05

    location_article_counts: dict[str, set[str]] = {}
    display_by_key: dict[str, str] = {}
    for article in cluster.articles:
        for location in article.signals.locations:
            key = _normalize_location(location)
            if not key:
                continue
            display_by_key.setdefault(key, location)
            location_article_counts.setdefault(key, set()).add(article.article_id)

    articles_with_locations = {
        article.article_id
        for article in cluster.articles
        if any(_normalize_location(location) for location in article.signals.locations)
    }

    if location_article_counts:
        shared = [
            display_by_key[key]
            for key, ids in location_article_counts.items()
            if len(ids) >= 2
        ]
        if shared:
            notes.append(f"Location guardrail: shared location signal(s) {', '.join(shared)}.")
            score += 0.15
        elif len(cluster.articles) == 1:
            notes.append(f"Location guardrail: location signal found: {', '.join(locations)}.")
            score += 0.05
        else:
            notes.append(
                "Location guardrail: location data is limited to one source or not corroborated; "
                "do not treat the place as fully confirmed."
            )
            score -= 0.05

        if len(location_article_counts) > 1 and len(articles_with_locations) > 1 and not shared:
            notes.append(
                "Location guardrail warning: different sources mention different places; "
                "verify they are context locations rather than separate event locations."
            )
            score -= 0.15
    else:
        notes.append("Location guardrail: no usable location signal found.")
        score -= 0.05

    return notes, max(0.0, min(1.0, round(score, 3)))
