from __future__ import annotations

from itertools import combinations

from .models import Article, StoryCluster
from .text_similarity import article_similarity


def _cluster_similarity(article: Article, cluster: list[Article]) -> float:
    if not cluster:
        return 0.0
    scores = [
        article_similarity(article.title, article.body, other.title, other.body)
        for other in cluster
    ]
    return max(scores)


def _average_pair_similarity(articles: list[Article]) -> float:
    if len(articles) < 2:
        return 1.0
    scores = [
        article_similarity(a.title, a.body, b.title, b.body)
        for a, b in combinations(articles, 2)
    ]
    return round(sum(scores) / len(scores), 4)


def _cluster_score(articles: list[Article], avg_similarity: float) -> float:
    weighted_support = sum(a.source.support_weight for a in articles)
    distinct_sources = len({a.source.name for a in articles})

    # Prototype scoring:
    # - same story repeated by several reliable sources matters most
    # - similarity prevents unrelated articles from scoring highly
    # - distinct sources are rewarded more than duplicate files from one outlet
    score = (weighted_support * 0.65) + (distinct_sources * 0.25) + (avg_similarity * 0.10)
    return round(score, 3)


def cluster_articles(articles: list[Article], threshold: float = 0.22) -> list[StoryCluster]:
    raw_clusters: list[list[Article]] = []

    # Longer texts first gives more stable cluster anchors.
    for article in sorted(articles, key=lambda a: len(a.body), reverse=True):
        best_index = -1
        best_similarity = 0.0

        for i, cluster in enumerate(raw_clusters):
            sim = _cluster_similarity(article, cluster)
            if sim > best_similarity:
                best_similarity = sim
                best_index = i

        if best_index >= 0 and best_similarity >= threshold:
            raw_clusters[best_index].append(article)
        else:
            raw_clusters.append([article])

    clusters: list[StoryCluster] = []
    for i, articles_in_cluster in enumerate(raw_clusters, start=1):
        avg_sim = _average_pair_similarity(articles_in_cluster)
        clusters.append(
            StoryCluster(
                cluster_id=i,
                articles=articles_in_cluster,
                score=_cluster_score(articles_in_cluster, avg_sim),
                avg_similarity=avg_sim,
            )
        )

    return sorted(clusters, key=lambda c: c.score, reverse=True)
