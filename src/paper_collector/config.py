from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import Topic


@dataclass(frozen=True, slots=True)
class Settings:
    daily_limit: int
    candidate_limit: int
    shortlist_limit: int
    llm_assessment_limit: int
    exploration_slots: int
    arxiv_categories: list[str]
    anchor_terms: list[str]
    topics: list[Topic]
    keyword_gate: float = 0.30
    semantic_gate: float = 60.0
    relevance_floor: float = 30.0
    history_days: int = 14


def load_settings(path: str | Path) -> Settings:
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    collector = raw["collector"]
    topics = [Topic(**item) for item in raw["topic"]]
    return Settings(
        daily_limit=int(collector["daily_limit"]),
        candidate_limit=int(collector["candidate_limit"]),
        shortlist_limit=int(collector.get("shortlist_limit", 40)),
        llm_assessment_limit=int(collector.get("llm_assessment_limit", 20)),
        exploration_slots=int(collector.get("exploration_slots", 2)),
        arxiv_categories=list(collector["arxiv_categories"]),
        anchor_terms=list(collector.get("anchor_terms", ["llm", "language model"])),
        topics=topics,
        keyword_gate=float(collector.get("keyword_gate", 0.30)),
        semantic_gate=float(collector.get("semantic_gate", 60.0)),
        relevance_floor=float(collector.get("relevance_floor", 30.0)),
        history_days=int(collector.get("history_days", 14)),
    )
