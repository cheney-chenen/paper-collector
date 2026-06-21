from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import Topic


@dataclass(frozen=True, slots=True)
class Settings:
    daily_limit: int
    candidate_limit: int
    arxiv_categories: list[str]
    topics: list[Topic]


def load_settings(path: str | Path) -> Settings:
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    collector = raw["collector"]
    topics = [Topic(**item) for item in raw["topic"]]
    return Settings(
        daily_limit=int(collector["daily_limit"]),
        candidate_limit=int(collector["candidate_limit"]),
        arxiv_categories=list(collector["arxiv_categories"]),
        topics=topics,
    )
