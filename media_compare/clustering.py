from __future__ import annotations

from itertools import combinations

from .guardrails import check_merge_guardrail, cluster_guardrail_notes
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


def _best_neighbor_scores(articles: list[Article]) -> list[float]:
    if len(articles) < 2:
        return []

    scores: list[float] = []
    for article in articles:
        best = max(
            article_similarity(article.title, article.body, other.title, other.body)
            for other in articles
            if other is not article
        )
        scores.append(best)
    return scores


def _average_best_neighbor_similarity(articles: list[Article]) -> float:
    scores = _best_neighbor_scores(articles)
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def _similarity_coverage(articles: list[Article], threshold: float) -> float:
    """How many articles have at least one solid local neighbor in the cluster.

    Average pair similarity naturally falls as clusters grow because not every article
    repeats every detail. This metric is more tolerant: each article only needs one
    good bridge to the story.
    """
    scores = _best_neighbor_scores(articles)
    if not scores:
        return 0.0
    covered = sum(1 for score in scores if score >= threshold)
    return round(covered / len(scores), 4)


def _cluster_score(
    articles: list[Article],
    avg_similarity: float,
    similarity_coverage: float,
    guardrail_score: float,
) -> float:
    weighted_support = sum(a.source.support_weight for a in articles)
    distinct_sources = len({a.source.name for a in articles})

    # Prototype scoring:
    # - same story repeated by several reliable sources matters most
    # - similarity coverage is used because average similarity drops as clusters grow
    # - date/location guardrails support clusters that are consistent on event context
    # - distinct sources are rewarded more than duplicate files from one outlet
    score = (
        (weighted_support * 0.58)
        + (distinct_sources * 0.22)
        + (similarity_coverage * 0.12)
        + (avg_similarity * 0.03)
        + (guardrail_score * 0.05)
    )
    return round(score, 3)


def cluster_articles(articles: list[Article], threshold: float = 0.22) -> list[StoryCluster]:
    raw_clusters: list[list[Article]] = []

    # Longer texts first gives more stable cluster anchors.
    for article in sorted(articles, key=lambda a: len(a.body), reverse=True):
        best_index = -1
        best_similarity = 0.0

        for i, cluster in enumerate(raw_clusters):
            guardrail = check_merge_guardrail(article, cluster)
            if not guardrail.allow:
                continue

            sim = _cluster_similarity(article, cluster)
            adjusted_similarity = sim + guardrail.bonus
            if adjusted_similarity > best_similarity:
                best_similarity = adjusted_similarity
                best_index = i

        if best_index >= 0 and best_similarity >= threshold:
            raw_clusters[best_index].append(article)
        else:
            raw_clusters.append([article])

    clusters: list[StoryCluster] = []
    for i, articles_in_cluster in enumerate(raw_clusters, start=1):
        avg_sim = _average_pair_similarity(articles_in_cluster)
        avg_best_sim = _average_best_neighbor_similarity(articles_in_cluster)
        coverage = _similarity_coverage(articles_in_cluster, threshold)

        provisional = StoryCluster(
            cluster_id=i,
            articles=articles_in_cluster,
            score=0.0,
            avg_similarity=avg_sim,
            avg_best_similarity=avg_best_sim,
            similarity_coverage=coverage,
        )
        notes, guardrail_score = cluster_guardrail_notes(provisional)
        provisional.guardrail_notes = notes
        provisional.guardrail_score = guardrail_score
        provisional.score = _cluster_score(articles_in_cluster, avg_sim, coverage, guardrail_score)
        clusters.append(provisional)

    return sorted(clusters, key=lambda c: c.score, reverse=True)
