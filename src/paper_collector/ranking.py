from __future__ import annotations

import math
import re
from collections import Counter

from .models import Paper, Topic

DEFAULT_ANCHORS = ["llm", "large language model", "language model", "foundation model", "transformer"]
MIN_KEYWORD_RELEVANCE = 0.30
DEFAULT_SEMANTIC_GATE = 60.0
KEYWORD_WEIGHT = 0.35
SEMANTIC_WEIGHT = 0.65
LLM_RELEVANCE_WEIGHT = 0.4
EVIDENCE_TERMS = ["experiment", "benchmark", "baseline", "ablation", "evaluate", "dataset", "outperform", "speedup"]
PRACTICAL_TERMS = ["latency", "throughput", "memory", "cost", "speedup", "efficient", "gpu", "serving", "training time", "scalab"]
COMMON_TOKENS = {"the", "and", "for", "with", "from", "that", "this", "language", "model", "models", "llm", "large", "using"}


def _excluded(text: str, topics: list[Topic]) -> bool:
    """Any topic's exclude term blocks the paper globally — off-domain noise is dropped
    regardless of other topic matches. This is intentional, not per-topic filtering."""
    return any(term.casefold() in text for topic in topics for term in topic.exclude)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.casefold()) if token not in COMMON_TOKENS}


def _keyword_topics(paper: Paper, topics: list[Topic]) -> dict[str, float]:
    title = paper.title.casefold()
    abstract = paper.abstract.casefold()
    scores: dict[str, float] = {}
    for topic in topics:
        combined = f"{title} {abstract}"
        if any(term.casefold() in combined for term in topic.exclude):
            continue
        title_hits = sum(term.casefold() in title for term in topic.keywords)
        abstract_hits = sum(term.casefold() in abstract for term in topic.keywords)
        if title_hits or abstract_hits:
            # A title hit is stronger than several incidental abstract mentions.
            scores[topic.slug] = _clamp(45 * title_hits + 18 * abstract_hits) / 100
    return scores


def _evidence_score(text: str) -> float:
    terms = sum(term in text for term in EVIDENCE_TERMS)
    numbers = len(re.findall(r"\b\d+(?:\.\d+)?(?:%|x|×|b|m)?\b", text))
    comparison = any(term in text for term in ["compared", "versus", "than", "relative to", "over baseline"])
    return _clamp(22 + 9 * min(terms, 5) + 4 * min(numbers, 5) + 12 * comparison)


def _practical_score(text: str, paper: Paper) -> float:
    terms = sum(term in text for term in PRACTICAL_TERMS)
    quantitative = bool(re.search(r"\b\d+(?:\.\d+)?(?:%|x|×)\b", text))
    return _clamp(18 + 9 * min(terms, 6) + 14 * quantitative + 12 * bool(paper.code_url))


def _credibility_score(paper: Paper) -> float:
    score = 15
    score += 12 if len(paper.authors) >= 2 else 5
    score += 8 if len(paper.abstract) >= 500 else 2
    score += 38 if paper.venue else 0
    score += 22 if paper.code_url else 0
    if paper.cited_by_count:
        score += min(12, 3 * math.log1p(paper.cited_by_count))
    return _clamp(score)


def _novelty_scores(papers: list[Paper]) -> dict[str, float]:
    token_sets = {paper.paper_id: _tokens(f"{paper.title} {paper.abstract}") for paper in papers}
    result: dict[str, float] = {}
    for paper in papers:
        own = token_sets[paper.paper_id]
        similarities: list[float] = []
        for other in papers:
            if other.paper_id == paper.paper_id:
                continue
            theirs = token_sets[other.paper_id]
            if own and theirs:
                similarities.append(len(own & theirs) / len(own | theirs))
        result[paper.paper_id] = round(_clamp(100 * (1 - 1.5 * max(similarities, default=0)), 25, 100), 1)
    return result


def _weighted_score(parts: dict[str, float | None]) -> float:
    weights = {"relevance": 35, "quality": 25, "novelty": 15, "practical": 10, "credibility": 10, "personal": 5}
    available = [(weights[name], value) for name, value in parts.items() if value is not None]
    total_weight = sum(weight for weight, _ in available)
    return sum(weight * float(value) for weight, value in available) / total_weight if total_weight else 0.0


def _recompute(paper: Paper) -> None:
    keyword_relevance = 100 * max(paper.topic_scores.values(), default=0)
    relevance = keyword_relevance
    if paper.semantic_score is not None:
        relevance = KEYWORD_WEIGHT * keyword_relevance + SEMANTIC_WEIGHT * paper.semantic_score
    if "relevance" in paper.llm_scores:
        relevance = (1 - LLM_RELEVANCE_WEIGHT) * relevance + LLM_RELEVANCE_WEIGHT * paper.llm_scores["relevance"]

    text = f"{paper.title} {paper.abstract}".casefold()
    quality = paper.llm_scores.get("quality", _evidence_score(text))
    novelty = paper.llm_scores.get("novelty", paper.score_breakdown.get("novelty", 55.0))
    practical = paper.llm_scores.get("practical", _practical_score(text, paper))
    credibility = _credibility_score(paper)
    parts: dict[str, float | None] = {
        "relevance": round(relevance, 1), "quality": round(quality, 1), "novelty": round(novelty, 1),
        "practical": round(practical, 1), "credibility": round(credibility, 1), "personal": paper.personal_score,
    }
    paper.score_breakdown = {name: value for name, value in parts.items() if value is not None}
    paper.score = round(_weighted_score(parts), 1)
    if "confidence" in paper.llm_scores:
        paper.confidence = round(paper.llm_scores["confidence"], 1)
    else:
        paper.confidence = round(_clamp(35 + 8 * sum(term in text for term in EVIDENCE_TERMS) + 12 * bool(paper.venue)), 1)


def classify_and_score(
    paper: Paper, topics: list[Topic], anchor_terms: list[str] | None = None,
    keyword_gate: float = MIN_KEYWORD_RELEVANCE, semantic_gate: float = DEFAULT_SEMANTIC_GATE,
) -> Paper:
    """Hybrid relevance gate: a paper passes via the keyword path OR the semantic path.

    The keyword path reproduces the original behavior (anchor term + strong keyword match).
    The semantic path rescues novel-wording papers when an embedding score is available.
    Without embeddings, semantic_score is None and only the keyword path is live.
    """
    text = f"{paper.title} {paper.abstract}".casefold()
    anchors = anchor_terms or DEFAULT_ANCHORS
    seeded = dict(paper.topic_scores)  # semantic fallback topic seeded by add_semantic_scores
    if _excluded(text, topics):
        paper.score = 0.0
        paper.score_reasons = ["命中排除项"]
        return paper
    keyword_topics = _keyword_topics(paper, topics)
    anchor_ok = any(anchor.casefold() in text for anchor in anchors)
    keyword_path = anchor_ok and max(keyword_topics.values(), default=0) >= keyword_gate
    semantic_path = paper.semantic_score is not None and paper.semantic_score >= semantic_gate
    if not (keyword_path or semantic_path):
        paper.score = 0.0
        paper.score_reasons = ["未达关键词或语义相关阈值"]
        return paper
    if keyword_topics:
        paper.topic_scores = keyword_topics
        matched = [topic.title for topic in topics if topic.slug in keyword_topics]
        paper.score_reasons = [f"命中主题：{'、'.join(matched)}"]
    else:
        paper.topic_scores = seeded
        matched = [topic.title for topic in topics if topic.slug in seeded]
        paper.score_reasons = [f"语义相关主题：{'、'.join(matched)}"] if matched else ["语义相关"]
    if paper.venue:
        paper.score_reasons.append(f"已录用至 {paper.venue}")
    if paper.code_url:
        paper.score_reasons.append("附带代码链接")
    _recompute(paper)
    return paper


def rescore(papers: list[Paper]) -> list[Paper]:
    """Recompute final scores after embeddings, LLM assessment, or feedback are added."""
    labels = {"relevance": "匹配", "quality": "质量", "novelty": "新颖", "practical": "实用", "credibility": "可信", "personal": "偏好"}
    for paper in papers:
        _recompute(paper)
        strongest = sorted(paper.score_breakdown.items(), key=lambda item: item[1], reverse=True)[:2]
        base_reasons = [reason for reason in paper.score_reasons if not reason.startswith("优势：")]
        paper.score_reasons = base_reasons[:3] + [f"优势：{'、'.join(f'{labels[name]} {value:.0f}' for name, value in strongest)}"]
    return papers


def _primary_topic(paper: Paper) -> str:
    return max(paper.topic_scores, key=paper.topic_scores.get)


def select_diverse(papers: list[Paper], limit: int, exploration_slots: int = 2) -> list[Paper]:
    ranked = sorted(papers, key=lambda item: (item.score, item.updated), reverse=True)
    selected: list[Paper] = []
    topic_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()

    def add(paper: Paper, enforce_topic_cap: bool = True) -> bool:
        if paper in selected:
            return False
        topic = _primary_topic(paper)
        author = paper.authors[0] if paper.authors else "unknown"
        if enforce_topic_cap and topic_counts[topic] >= 4:
            return False
        if author_counts[author] >= 2:
            return False
        selected.append(paper)
        topic_counts[topic] += 1
        author_counts[author] += 1
        return True

    exploit_target = max(0, limit - 2 - exploration_slots)
    for paper in ranked:
        if len(selected) >= exploit_target:
            break
        add(paper)

    represented = set(topic_counts)
    for paper in ranked:
        if len(selected) >= exploit_target + 2:
            break
        if _primary_topic(paper) not in represented and add(paper):
            represented.add(_primary_topic(paper))

    exploratory = sorted(
        (paper for paper in ranked if paper not in selected),
        key=lambda item: (item.score_breakdown.get("novelty", 0) + item.score_breakdown.get("practical", 0), item.score),
        reverse=True,
    )
    for paper in exploratory:
        if len(selected) >= limit:
            break
        add(paper)
    for paper in ranked:
        if len(selected) >= limit:
            break
        add(paper, enforce_topic_cap=False)
    return selected[:limit]


def rank(
    papers: list[Paper], topics: list[Topic], limit: int, anchor_terms: list[str] | None = None,
    shortlist_limit: int = 40, exploration_slots: int = 2,
) -> list[Paper]:
    relevant = [paper for paper in papers if classify_and_score(paper, topics, anchor_terms).score > 0]
    novelty = _novelty_scores(relevant)
    for paper in relevant:
        paper.score_breakdown["novelty"] = novelty[paper.paper_id]
    rescore(relevant)
    shortlist = sorted(relevant, key=lambda item: item.score, reverse=True)[:shortlist_limit]
    return select_diverse(shortlist, limit, exploration_slots)
