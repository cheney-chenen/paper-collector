import unittest

from paper_collector.models import Paper, Topic
from paper_collector.ranking import rank


def paper(**overrides):
    values = {
        "paper_id": "x", "title": "Speculative decoding for LLM inference", "abstract": "We improve KV cache serving.", "authors": [],
        "published": "2026-06-22T00:00:00Z", "updated": "2026-06-22T00:00:00Z", "categories": [], "pdf_url": "", "abs_url": "",
    }
    values.update(overrides)
    return Paper(**values)


class RankingTests(unittest.TestCase):
    def test_relevant_paper_is_scored_and_explained(self):
        topic = Topic("serving", "推理系统", ["llm inference", "speculative decoding", "kv cache"])
        ranked = rank([paper()], [topic], 3)
        self.assertEqual(len(ranked), 1)
        self.assertGreater(ranked[0].score, 0)
        self.assertIn("命中主题", ranked[0].score_reasons[0])

    def test_excluded_paper_is_not_selected(self):
        topic = Topic("serving", "推理系统", ["serving"], ["speech recognition"])
        ranked = rank([paper(abstract="Serving for speech recognition")], [topic], 3)
        self.assertEqual(ranked[0].score, 0.0)
        self.assertEqual(ranked[0].topic_scores, {})

    def test_venue_and_code_increase_score(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        base, enhanced = rank([paper(), paper(paper_id="y", venue="MLSys", code_url="https://example.com")], [topic], 2)
        self.assertEqual(enhanced.paper_id, "x")
        self.assertGreater(base.score, enhanced.score)
