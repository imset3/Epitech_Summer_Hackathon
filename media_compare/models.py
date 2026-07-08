from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceProfile:
    name: str
    aliases: list[str]
    trust: float
    reach: float
    notes: str = ""

    @property
    def support_weight(self) -> float:
        """How much this source counts when several outlets report the same story.

        trust is intentionally stronger than reach. A highly visible but less
        reliable source should not dominate a more careful source.
        """
        return round((self.trust * 0.85) + (self.reach * 0.15), 3)


@dataclass
class ArticleSignals:
    dates: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)


@dataclass
class Article:
    article_id: str
    path: str
    source: SourceProfile
    title: str
    body: str
    metadata: dict[str, str] = field(default_factory=dict)
    signals: ArticleSignals = field(default_factory=ArticleSignals)

    @property
    def short_name(self) -> str:
        return f"{self.source.name}: {self.title}"


@dataclass
class StoryCluster:
    cluster_id: int
    articles: list[Article]
    score: float
    avg_similarity: float
    avg_best_similarity: float = 0.0
    similarity_coverage: float = 0.0
    guardrail_notes: list[str] = field(default_factory=list)
    guardrail_score: float = 0.0

    @property
    def distinct_sources(self) -> list[str]:
        seen: list[str] = []
        for article in self.articles:
            if article.source.name not in seen:
                seen.append(article.source.name)
        return seen

    @property
    def weighted_support(self) -> float:
        return round(sum(a.source.support_weight for a in self.articles), 3)

    @property
    def source_count(self) -> int:
        return len(self.distinct_sources)

    def to_prompt_payload(self, max_chars_per_article: int = 3500) -> dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "weighted_support": self.weighted_support,
            "distinct_sources": self.distinct_sources,
            "articles": [
                {
                    "source": a.source.name,
                    "trust": a.source.trust,
                    "reach": a.source.reach,
                    "support_weight": a.source.support_weight,
                    "title": a.title,
                    "document": a.path,
                    "url": a.metadata.get("url", ""),
                    "dates": a.signals.dates,
                    "years": a.signals.years,
                    "locations": a.signals.locations,
                    "text": a.body[:max_chars_per_article],
                }
                for a in self.articles
            ],
        }
