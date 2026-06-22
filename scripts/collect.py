#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from paper_collector.arxiv import fetch_recent
from paper_collector.config import load_settings
from paper_collector.llm import add_semantic_scores, assess_papers, summarize_in_chinese
from paper_collector.ranking import cull_off_topic, prepare_candidates, rescore, select_diverse
from paper_collector.storage import (
    canonical_paper_id,
    load_daily_papers,
    load_recent_selected,
    save_daily,
    seen_before,
    update_index,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and rank recent arXiv papers.")
    parser.add_argument("--config", default=ROOT / "topics.toml", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--offline", action="store_true", help="Build from the existing daily file without a network request.")
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.offline:
        print("Offline mode does not fetch new papers.")
        return
    user_agent = os.environ.get("ARXIV_USER_AGENT") or "paper-collector/0.1 (personal research use)"
    data_root = ROOT / "data"
    previous_ids = seen_before(data_root, args.date)
    existing = [paper for paper in load_daily_papers(data_root, args.date) if canonical_paper_id(paper.paper_id) not in previous_ids]
    fetched = fetch_recent(settings.arxiv_categories, settings.candidate_limit, user_agent)
    candidates = existing + [paper for paper in fetched if canonical_paper_id(paper.paper_id) not in previous_ids]
    # Keep the newest arXiv version while making same-day reruns idempotent.
    papers_by_id = {canonical_paper_id(paper.paper_id): paper for paper in candidates}
    papers = list(papers_by_id.values())
    history = load_recent_selected(data_root, args.date, settings.history_days)
    add_semantic_scores(papers, settings.topics)
    pool = prepare_candidates(
        papers, settings.topics, settings.anchor_terms,
        settings.keyword_gate, settings.semantic_gate, history_papers=history,
    )
    shortlist = sorted(pool, key=lambda item: item.score, reverse=True)[: settings.shortlist_limit]
    assess_papers(shortlist, settings.llm_assessment_limit)
    rescore(shortlist)
    kept = cull_off_topic(shortlist, settings.relevance_floor, settings.daily_limit)
    ranked = select_diverse(kept, settings.daily_limit, settings.exploration_slots)
    summarize_in_chinese(ranked)
    save_daily(data_root, args.date, ranked, candidate_count=len(papers))
    update_index(data_root, ranked)
    print(f"Saved {len(ranked)} selected papers from {len(papers)} unseen candidates for {args.date.isoformat()}.")


if __name__ == "__main__":
    main()
