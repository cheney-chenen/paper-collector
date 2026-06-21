from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Topic:
    slug: str
    title: str
    keywords: list[str]
    exclude: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Paper:
    paper_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    updated: str
    categories: list[str]
    pdf_url: str
    abs_url: str
    source: str = "arXiv"
    venue: str | None = None
    code_url: str | None = None
    cited_by_count: int | None = None
    topic_scores: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    score_reasons: list[str] = field(default_factory=list)
    summary_zh: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
