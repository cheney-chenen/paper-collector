import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from paper_collector.config import load_settings
from paper_collector.models import Paper
from paper_collector.storage import load_daily_papers, save_daily
from scripts import collect


def candidate(paper_id="2610.00001v1"):
    return Paper(paper_id, "LLM inference with KV cache", "Efficient model serving with a KV cache.",
                 ["Ada", "Grace"], "2026-10-23T00:00:00Z", "2026-10-23T00:00:00Z", ["cs.CL"],
                 f"https://arxiv.org/pdf/{paper_id}", f"https://arxiv.org/abs/{paper_id}")


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings(collect.ROOT / "topics.toml")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for patcher in [patch.object(collect, "ROOT", self.root),
                        patch.object(collect, "load_settings", return_value=self.settings),
                        patch.dict(os.environ, {}, clear=True)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_source_failure_preserves_existing_daily_file(self):
        target = save_daily(self.root / "data", date(2026, 10, 24), [candidate()])
        original = target.read_bytes()
        with patch.object(collect, "fetch_recent", side_effect=HTTPError("url", 429, "limited", {}, None)):
            with self.assertRaises(HTTPError):
                collect.main(["--date", "2026-10-24"])
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((self.root / "data" / "papers" / "index.json").exists())

    def test_default_edition_date_uses_configured_timezone(self):
        local_time = datetime(2026, 10, 24, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(collect, "datetime") as clock, patch.object(collect, "fetch_recent", return_value=[candidate()]):
            clock.now.return_value = local_time
            collect.main([])
            clock.now.assert_called_once_with(ZoneInfo("Asia/Shanghai"))
        self.assertEqual(len(load_daily_papers(self.root / "data", date(2026, 10, 24))), 1)

    def test_previous_day_versions_are_excluded_on_rerun(self):
        save_daily(self.root / "data", date(2026, 10, 23), [candidate()])
        with patch.object(collect, "fetch_recent", return_value=[candidate("2610.00001v2"), candidate("2610.00002v1")]):
            collect.main(["--date", "2026-10-24"])
            collect.main(["--date", "2026-10-24"])
        papers = load_daily_papers(self.root / "data", date(2026, 10, 24))
        self.assertEqual([paper.paper_id for paper in papers], ["2610.00002v1"])
