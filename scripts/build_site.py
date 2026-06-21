#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_collector.storage import read_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the selected daily JSON to the static dashboard.")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    daily = ROOT / "data" / "daily" / f"{args.date.isoformat()}.json"
    payload = read_json(daily, {"date": args.date.isoformat(), "papers": []})
    assert isinstance(payload, dict)
    destination = ROOT / "site" / "data"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / f"{args.date.isoformat()}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history = sorted(path.stem for path in (ROOT / "data" / "daily").glob("*.json")) if (ROOT / "data" / "daily").exists() else []
    (destination / "history.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    print(f"Dashboard data built for {payload['date']}.")


if __name__ == "__main__":
    main()
