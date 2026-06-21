import os
import unittest
from unittest.mock import patch

from paper_collector.llm import summarize_in_chinese
from paper_collector.models import Paper


class LlmTests(unittest.TestCase):
    def test_no_key_keeps_papers_local_and_unchanged(self):
        paper = Paper("id", "title", "abstract", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(summarize_in_chinese([paper])[0], paper)
            self.assertIsNone(paper.summary_zh)
