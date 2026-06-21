from __future__ import annotations

import math

from .models import Paper, Topic


def classify_and_score(paper: Paper, topics: list[Topic]) -> Paper:
    """Apply explainable cold-start ranking without a vendor-specific model."""
    text = f"{paper.title} {paper.abstract}".casefold()
    reasons: list[str] = []
    topic_scores: dict[str, float] = {}
    for topic in topics:
        if any(term.casefold() in text for term in topic.exclude):
            continue
        hits = sum(term.casefold() in text for term in topic.keywords)
        if hits:
            topic_scores[topic.slug] = min(1.0, hits / 3)

    relevance = max(topic_scores.values(), default=0.0)
    if relevance:
        matched = [topic.title for topic in topics if topic.slug in topic_scores]
        reasons.append(f"命中主题：{'、'.join(matched)}")
    else:
        paper.topic_scores = {}
        paper.score = 0.0
        paper.score_reasons = ["未命中当前主题词，保留以供人工复核"]
        return paper
    if paper.venue:
        reasons.append(f"已录用至 {paper.venue}")
    if paper.code_url:
        reasons.append("附带代码链接")
    impact = 0.0
    if paper.cited_by_count:
        impact = min(1.0, math.log1p(paper.cited_by_count) / math.log(101))
        reasons.append(f"已获 {paper.cited_by_count} 次引用")

    credibility = 1.0 if paper.venue else 0.25
    artifact = 1.0 if paper.code_url else 0.0
    paper.topic_scores = topic_scores
    paper.score = round(100 * (0.6 * relevance + 0.16 * credibility + 0.12 * artifact + 0.12 * impact), 1)
    paper.score_reasons = reasons or ["未命中当前主题词，保留以供人工复核"]
    return paper


def rank(papers: list[Paper], topics: list[Topic], limit: int) -> list[Paper]:
    for paper in papers:
        classify_and_score(paper, topics)
    return sorted(papers, key=lambda item: (item.score, item.updated), reverse=True)[:limit]
