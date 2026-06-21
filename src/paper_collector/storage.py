from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .models import Paper


def read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_daily(root: Path, run_date: date, papers: list[Paper]) -> Path:
    target = root / "daily" / f"{run_date.isoformat()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"date": run_date.isoformat(), "papers": [paper.to_dict() for paper in papers]}, ensure_ascii=False, indent=2),
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
