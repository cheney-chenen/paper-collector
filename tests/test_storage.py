import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from paper_collector.models import Paper
from paper_collector.storage import save_daily, update_index


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
