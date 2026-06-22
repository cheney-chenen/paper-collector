import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from paper_collector.models import Paper
from paper_collector.storage import (
    canonical_paper_id,
    load_daily_papers,
    load_recent_selected,
    save_daily,
    seen_before,
    update_index,
)


def sample() -> Paper:
    return Paper("2601.00001", "A paper", "abstract", ["Ada"], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "pdf", "abs")


class StorageTests(unittest.TestCase):
    def test_daily_and_index_are_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            daily = save_daily(root, date(2026, 1, 1), [sample()])
            index = update_index(root, [sample()])
            self.assertEqual(json.loads(daily.read_text())["papers"][0]["paper_id"], "2601.00001")
            self.assertIn("2601.00001", json.loads(index.read_text()))

    def test_arxiv_versions_share_one_canonical_id(self):
        self.assertEqual(canonical_paper_id("2601.00001v3"), "2601.00001")

    def test_seen_before_excludes_current_day(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_daily(root, date(2026, 1, 1), [sample()])
            newer = sample()
            newer.paper_id = "2601.00002v2"
            save_daily(root, date(2026, 1, 2), [newer])
            self.assertEqual(seen_before(root, date(2026, 1, 2)), {"2601.00001"})
            self.assertEqual(load_daily_papers(root, date(2026, 1, 2))[0].paper_id, "2601.00002v2")

    def test_load_recent_selected_respects_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = sample()
            old.paper_id = "old"
            recent = sample()
            recent.paper_id = "recent"
            save_daily(root, date(2026, 1, 1), [old])     # 9 days before run date
            save_daily(root, date(2026, 1, 8), [recent])  # 2 days before run date
            loaded = load_recent_selected(root, date(2026, 1, 10), days=7)
            self.assertEqual([p.paper_id for p in loaded], ["recent"])

    def test_load_recent_selected_includes_exact_cutoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edge = sample()
            edge.paper_id = "edge"
            # run_date 2026-01-10, days=7 -> cutoff 2026-01-03, which must be INCLUDED (>=).
            save_daily(root, date(2026, 1, 3), [edge])
            loaded = load_recent_selected(root, date(2026, 1, 10), days=7)
            self.assertEqual([p.paper_id for p in loaded], ["edge"])

    def test_load_recent_selected_skips_non_date_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = sample()
            real.paper_id = "real"
            save_daily(root, date(2026, 1, 8), [real])
            (root / "daily" / "summary.json").write_text("{}", encoding="utf-8")
            loaded = load_recent_selected(root, date(2026, 1, 10), days=7)
            self.assertEqual([p.paper_id for p in loaded], ["real"])
