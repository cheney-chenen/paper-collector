from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .models import Paper


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_paper_id(paper_id: str) -> str:
    """Collapse arXiv versions so v2 is not recommended as a brand-new paper."""
    return re.sub(r"v\d+$", "", paper_id)


def load_daily_papers(root: Path, run_date: date) -> list[Paper]:
    payload = read_json(root / "daily" / f"{run_date.isoformat()}.json", {"papers": []})
    assert isinstance(payload, dict)
    allowed = {field.name for field in fields(Paper)}
    return [Paper(**{key: value for key, value in item.items() if key in allowed}) for item in payload.get("papers", [])]


def load_recent_selected(root: Path, run_date: date, days: int) -> list[Paper]:
    """Selected papers from daily files in [run_date - days, run_date), for novelty history."""
    papers: list[Paper] = []
    daily_root = root / "daily"
    if not daily_root.exists() or days <= 0:
        return papers
    cutoff = run_date - timedelta(days=days)
    for path in sorted(daily_root.glob("*.json")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if cutoff <= file_date < run_date:
            papers.extend(load_daily_papers(root, file_date))
    return papers


def seen_before(root: Path, run_date: date) -> set[str]:
    seen: set[str] = set()
    daily_root = root / "daily"
    if not daily_root.exists():
        return seen
    for path in daily_root.glob("*.json"):
        if path.stem >= run_date.isoformat():
            continue
        payload = read_json(path, {"papers": []})
        assert isinstance(payload, dict)
        seen.update(canonical_paper_id(item["paper_id"]) for item in payload.get("papers", []))
    return seen


def save_daily(root: Path, run_date: date, papers: list[Paper], candidate_count: int | None = None) -> Path:
    target = root / "daily" / f"{run_date.isoformat()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({
            "date": run_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_count": candidate_count,
            "selected_count": len(papers),
            "papers": [paper.to_dict() for paper in papers],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def update_index(root: Path, papers: list[Paper]) -> Path:
    target = root / "papers" / "index.json"
    current = read_json(target, {})
    assert isinstance(current, dict)
    current.update({paper.paper_id: paper.to_dict() for paper in papers})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
