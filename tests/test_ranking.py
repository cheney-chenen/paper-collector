import unittest

from paper_collector.models import Paper, Topic
from paper_collector.ranking import classify_and_score, cull_off_topic, prepare_candidates, rank, rescore


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
        self.assertEqual(ranked, [])

    def test_venue_and_code_increase_score(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        base, enhanced = rank([paper(), paper(paper_id="y", venue="MLSys", code_url="https://example.com")], [topic], 2)
        self.assertEqual(enhanced.paper_id, "x")
        self.assertGreater(base.score, enhanced.score)

    def test_non_llm_paper_fails_anchor_gate(self):
        topic = Topic("serving", "推理系统", ["serving"])
        self.assertEqual(rank([paper(title="Efficient database serving", abstract="Serving SQL queries")], [topic], 3), [])

    def test_single_incidental_abstract_hit_is_filtered(self):
        topic = Topic("serving", "推理系统", ["serving"])
        candidate = paper(title="Language model evaluation", abstract="The appendix mentions serving once.")
        self.assertEqual(rank([candidate], [topic], 3), [])

    def test_score_contains_explainable_dimensions(self):
        topic = Topic("serving", "推理系统", ["speculative decoding", "kv cache"])
        selected = rank([paper()], [topic], 1)[0]
        self.assertEqual({"relevance", "quality", "novelty", "practical", "credibility"}, set(selected.score_breakdown))
        self.assertGreater(selected.confidence, 0)

    def test_selection_preserves_topic_diversity(self):
        topics = [Topic("serving", "推理系统", ["speculative decoding"]), Topic("alignment", "对齐", ["alignment"])]
        candidates = [paper(paper_id=f"s{i}", title=f"LLM speculative decoding system {i}") for i in range(6)]
        candidates += [paper(paper_id="a1", title="LLM alignment method", abstract="Language model alignment with experiment and benchmark")]
        selected = rank(candidates, topics, 5)
        self.assertTrue(any("alignment" in item.topic_scores for item in selected))

    def test_rescoring_does_not_duplicate_explanations(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        selected = rank([paper()], [topic], 1)
        rescore(selected)
        self.assertEqual(sum(reason.startswith("优势：") for reason in selected[0].score_reasons), 1)

    def test_semantic_path_rescues_paper_without_keywords(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        candidate = paper(
            title="Latent retrieval over large corpora",
            abstract="A new index structure for retrieval.",
            semantic_score=75.0,
            topic_scores={"serving": 0.75},
        )
        scored = classify_and_score(candidate, [topic])
        self.assertGreater(scored.score, 0)
        self.assertEqual(max(scored.topic_scores, key=scored.topic_scores.get), "serving")

    def test_paper_with_no_keyword_or_semantic_signal_is_dropped(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        candidate = paper(
            title="Latent retrieval over corpora",
            abstract="A new index structure.",
            semantic_score=20.0,
        )
        self.assertEqual(classify_and_score(candidate, [topic]).score, 0.0)

    def test_exclude_blocks_even_with_semantic_signal(self):
        topic = Topic("serving", "推理系统", ["serving"], ["speech recognition"])
        candidate = paper(
            title="Speech recognition serving",
            abstract="Serving for speech recognition.",
            semantic_score=95.0,
            topic_scores={"serving": 0.9},
        )
        self.assertEqual(classify_and_score(candidate, [topic]).score, 0.0)

    def test_exclude_is_global_across_topics(self):
        topics = [
            Topic("pretraining", "预训练", ["pretraining"], ["speech recognition"]),
            Topic("serving", "推理系统", ["speculative decoding"]),
        ]
        # Matches the serving keyword and has the LLM anchor, but the abstract contains
        # pretraining's exclude term — global exclusion must drop it anyway.
        candidate = paper(
            title="Speculative decoding for LLM inference",
            abstract="We speed up speech recognition pipelines.",
        )
        self.assertEqual(classify_and_score(candidate, topics).score, 0.0)

    def test_semantic_score_dominates_relevance(self):
        topic = Topic("serving", "推理系统", ["speculative decoding", "kv cache"])
        candidate = paper(semantic_score=90.0)
        classify_and_score(candidate, [topic])
        # keyword_relevance = 63 (one title + one abstract hit); semantic = 90.
        # new blend = 0.35*63 + 0.65*90 = 80.55  (old 0.6/0.4 blend would be 73.8)
        self.assertAlmostEqual(candidate.score_breakdown["relevance"], 80.5, delta=1.0)

    def test_history_reduces_novelty(self):
        topic = Topic("serving", "推理系统", ["speculative decoding", "kv cache"])
        twin = paper(paper_id="hist")
        with_history = prepare_candidates([paper(paper_id="n1")], [topic], history_papers=[twin])
        without_history = prepare_candidates([paper(paper_id="n2")], [topic])
        # Identical twin in history → Jaccard 1.0 → clamp floor; no peers/history → max novelty.
        self.assertEqual(with_history[0].score_breakdown["novelty"], 25.0)
        self.assertEqual(without_history[0].score_breakdown["novelty"], 100.0)

    def test_prepare_candidates_drops_irrelevant(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        off = paper(paper_id="off", title="Database indexing", abstract="B-tree storage.")
        kept = prepare_candidates([paper(paper_id="on"), off], [topic])
        self.assertEqual([p.paper_id for p in kept], ["on"])

    def test_cull_drops_assessed_off_topic_paper(self):
        keep = paper(paper_id="keep")
        keep.llm_scores = {"relevance": 80.0}
        keep.score = 80.0
        drop = paper(paper_id="drop")
        drop.llm_scores = {"relevance": 10.0}
        drop.score = 70.0
        kept = cull_off_topic([keep, drop], relevance_floor=30.0, min_keep=1)
        self.assertEqual([p.paper_id for p in kept], ["keep"])

    def test_cull_never_drops_below_min_keep(self):
        high = paper(paper_id="high")
        high.llm_scores = {"relevance": 10.0}
        high.score = 90.0
        low = paper(paper_id="low")
        low.llm_scores = {"relevance": 5.0}
        low.score = 80.0
        kept = cull_off_topic([high, low], relevance_floor=30.0, min_keep=2)
        self.assertEqual({p.paper_id for p in kept}, {"high", "low"})

    def test_cull_keeps_unassessed_papers(self):
        unassessed = paper(paper_id="u")  # no llm_scores at all
        kept = cull_off_topic([unassessed], relevance_floor=30.0, min_keep=1)
        self.assertEqual([p.paper_id for p in kept], ["u"])
