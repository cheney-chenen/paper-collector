import os
import unittest
from io import BytesIO
from unittest.mock import patch

from paper_collector.llm import add_semantic_scores, assess_papers, summarize_in_chinese
from paper_collector.models import Paper, Topic


class LlmTests(unittest.TestCase):
    def test_empty_optional_base_url_uses_default_provider(self):
        paper = Paper("id", "title", "abstract", [], "2026-01-01", "2026-01-01", [], "", "")
        response = BytesIO(b'{"choices":[{"message":{"content":"A concise summary."}}]}')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model", "OPENAI_BASE_URL": ""}, clear=True):
            with patch("paper_collector.llm.urlopen", return_value=response) as request:
                summarize_in_chinese([paper])
        self.assertEqual(paper.summary_zh, "A concise summary.")
        self.assertEqual(request.call_args.args[0].full_url, "https://api.openai.com/v1/chat/completions")

    def test_model_outage_does_not_spend_a_timeout_on_every_paper(self):
        for action in [lambda papers: assess_papers(papers, 70), summarize_in_chinese]:
            with self.subTest(action=action), patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}, clear=True):
                papers = [Paper(str(index), "title", "abstract", [], "2026-01-01", "2026-01-01", [], "", "") for index in range(10)]
                with patch("paper_collector.llm._post", side_effect=TimeoutError("provider unavailable")) as post:
                    self.assertIs(action(papers), papers)
                self.assertEqual(post.call_count, 3)
                self.assertTrue(all(paper.summary_zh is None and not paper.llm_scores for paper in papers))

    def test_malformed_model_response_falls_back_to_original_abstract(self):
        paper = Paper("id", "title", "abstract", [], "2026-01-01", "2026-01-01", [], "", "")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test-model"}, clear=True):
            with patch("paper_collector.llm._post", return_value={"choices": []}):
                assess_papers([paper], 1)
                summarize_in_chinese([paper])
        self.assertIsNone(paper.summary_zh)
        self.assertFalse(paper.llm_scores)

    def test_no_key_keeps_papers_local_and_unchanged(self):
        paper = Paper("id", "title", "abstract", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(summarize_in_chinese([paper])[0], paper)
            self.assertIsNone(paper.summary_zh)

    def test_semantic_scores_seed_best_topic(self):
        topics = [Topic("serving", "推理系统", ["kv cache"]), Topic("align", "对齐", ["alignment"])]
        serving_paper = Paper("p1", "t", "a", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        align_paper = Paper("p2", "t", "a", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        response = {"data": [
            {"index": 0, "embedding": [1.0, 0.0]},   # topic serving
            {"index": 1, "embedding": [0.0, 1.0]},   # topic align
            {"index": 2, "embedding": [1.0, 0.0]},   # serving_paper -> serving
            {"index": 3, "embedding": [0.0, 1.0]},   # align_paper -> align
        ]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_EMBEDDING_MODEL": "m"}, clear=True):
            with patch("paper_collector.llm._post", return_value=response):
                add_semantic_scores([serving_paper, align_paper], topics)
        # cosine 1.0 maps to (1.0 - 0.15) / 0.7 * 100 = 121.4, clamped to 100.0
        self.assertEqual(serving_paper.semantic_score, 100.0)
        self.assertEqual(list(serving_paper.topic_scores), ["serving"])
        self.assertEqual(list(align_paper.topic_scores), ["align"])
