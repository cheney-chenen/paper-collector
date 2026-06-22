# Scoring v3 (Precision + Recall) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve daily paper selection on both precision and recall by making embeddings the primary relevance gate/signal, running the LLM filter over a wide score-ranked shortlist, culling LLM-judged off-topic papers, and penalizing novelty against recent history.

**Architecture:** Reorder the pipeline so strong signals decide membership instead of fine-tuning an already-filtered set. The hard substring gate becomes a hybrid keyword-OR-semantic gate; the shortlist is ranked by pure score (no diversity caps) so a hot topic's best papers all reach the LLM; the LLM assesses the whole shortlist; off-topic papers are culled before the final pick; diversity constraints apply only at the final 12-pick step. The key-less heuristic path is preserved as graceful fallback.

**Tech Stack:** Python 3.11+, stdlib `unittest`, dataclasses, `urllib` (OpenAI-compatible API). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-22-scoring-precision-recall-design.md`

---

## Conventions

- All commands run from the repo root: `/Users/cheney/Documents/paper_collector`.
- Run a single test: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_name -v`
- Run a whole module: `PYTHONPATH=src python3 -m unittest tests.test_ranking -v`
- Run everything: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- Commit trailer (every commit): `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/paper_collector/config.py` | `Settings` + `load_settings` | Add 4 tunable fields |
| `topics.toml` | Operator config | Widen limits, add gate/floor/history keys |
| `src/paper_collector/ranking.py` | Gating, scoring, novelty, cull, selection | Hybrid gate, reweight, `prepare_candidates`, `cull_off_topic`, history novelty |
| `src/paper_collector/llm.py` | Embeddings + LLM assessment | Per-topic semantic seeding of `topic_scores` |
| `src/paper_collector/storage.py` | JSON persistence | `load_recent_selected` helper |
| `scripts/collect.py` | Pipeline wiring | New flow ordering |
| `tests/test_ranking.py` | Ranking tests | New tests for gate/reweight/novelty/cull |
| `tests/test_llm.py` | LLM tests | New test for semantic seeding |
| `tests/test_storage.py` | Storage tests | New test for `load_recent_selected` |

---

## Task 1: Config — add tunable fields

**Files:**
- Modify: `src/paper_collector/config.py`
- Modify: `topics.toml`
- Test: `tests/test_storage.py` is unaffected; config has no dedicated test — verify via a one-off load.

- [ ] **Step 1: Add the new fields to `Settings`**

In `src/paper_collector/config.py`, replace the `Settings` dataclass (lines 10-19) with:

```python
@dataclass(frozen=True, slots=True)
class Settings:
    daily_limit: int
    candidate_limit: int
    shortlist_limit: int
    llm_assessment_limit: int
    exploration_slots: int
    arxiv_categories: list[str]
    anchor_terms: list[str]
    topics: list[Topic]
    keyword_gate: float = 0.30
    semantic_gate: float = 60.0
    relevance_floor: float = 30.0
    history_days: int = 14
```

- [ ] **Step 2: Populate the new fields in `load_settings`**

In the same file, replace the `return Settings(...)` block (lines 27-36) with:

```python
    return Settings(
        daily_limit=int(collector["daily_limit"]),
        candidate_limit=int(collector["candidate_limit"]),
        shortlist_limit=int(collector.get("shortlist_limit", 40)),
        llm_assessment_limit=int(collector.get("llm_assessment_limit", 20)),
        exploration_slots=int(collector.get("exploration_slots", 2)),
        arxiv_categories=list(collector["arxiv_categories"]),
        anchor_terms=list(collector.get("anchor_terms", ["llm", "language model"])),
        topics=topics,
        keyword_gate=float(collector.get("keyword_gate", 0.30)),
        semantic_gate=float(collector.get("semantic_gate", 60.0)),
        relevance_floor=float(collector.get("relevance_floor", 30.0)),
        history_days=int(collector.get("history_days", 14)),
    )
```

- [ ] **Step 3: Update `topics.toml` operator config**

In `topics.toml`, replace the `[collector]` numeric lines (the current `shortlist_limit = 40` and `llm_assessment_limit = 20`) and add the new keys so the `[collector]` block reads:

```toml
[collector]
timezone = "Asia/Shanghai"
daily_limit = 12
candidate_limit = 180
shortlist_limit = 70
llm_assessment_limit = 70
exploration_slots = 2
keyword_gate = 0.30
semantic_gate = 60.0
relevance_floor = 30.0
history_days = 14
arxiv_categories = ["cs.CL", "cs.AI", "cs.LG", "cs.DC", "cs.SE"]
anchor_terms = ["llm", "large language model", "language model", "foundation model", "transformer", "attention model"]
```

- [ ] **Step 4: Verify the config loads with the new fields**

Run:
```bash
PYTHONPATH=src python3 -c "from paper_collector.config import load_settings; s = load_settings('topics.toml'); print(s.shortlist_limit, s.llm_assessment_limit, s.keyword_gate, s.semantic_gate, s.relevance_floor, s.history_days)"
```
Expected output: `70 70 0.3 60.0 30.0 14`

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
Expected: all tests PASS (no behavior change yet).

- [ ] **Step 6: Commit**

```bash
git add src/paper_collector/config.py topics.toml
git commit -m "$(cat <<'EOF'
feat: add scoring v3 config knobs (gates, floor, history, wider limits)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Hybrid gate + semantic-primary relevance reweighting

**Files:**
- Modify: `src/paper_collector/ranking.py`
- Test: `tests/test_ranking.py`

This task changes `classify_and_score` to a hybrid gate and flips `_recompute` to semantic-primary relevance. Existing `test_ranking.py` tests must stay green (they use no embeddings, so the keyword path stays identical).

- [ ] **Step 1: Write the failing tests**

Add these imports and tests to `tests/test_ranking.py`. Update the existing import line at the top:

```python
from paper_collector.ranking import classify_and_score, rank, rescore
```

Then append these test methods inside `class RankingTests`:

```python
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

    def test_semantic_score_dominates_relevance(self):
        topic = Topic("serving", "推理系统", ["speculative decoding", "kv cache"])
        candidate = paper(semantic_score=90.0)
        classify_and_score(candidate, [topic])
        # keyword_relevance = 63 (one title + one abstract hit); semantic = 90.
        # new blend = 0.35*63 + 0.65*90 = 80.55  (old 0.6/0.4 blend would be 73.8)
        self.assertAlmostEqual(candidate.score_breakdown["relevance"], 80.5, delta=1.0)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_semantic_path_rescues_paper_without_keywords tests.test_ranking.RankingTests.test_paper_with_no_keyword_or_semantic_signal_is_dropped tests.test_ranking.RankingTests.test_exclude_blocks_even_with_semantic_signal tests.test_ranking.RankingTests.test_semantic_score_dominates_relevance -v`

Expected: FAIL. `classify_and_score` is not exported with the new behavior; `test_semantic_score_dominates_relevance` fails on the old 0.6/0.4 blend (73.8 ≠ 80.5); the rescue test fails because the old hard gate zeroes a paper with no keyword hit.

- [ ] **Step 3: Add the new constants and the exclude helper**

In `src/paper_collector/ranking.py`, replace the constants block (lines 9-13) with:

```python
DEFAULT_ANCHORS = ["llm", "large language model", "language model", "foundation model", "transformer"]
MIN_KEYWORD_RELEVANCE = 0.30
DEFAULT_SEMANTIC_GATE = 60.0
KEYWORD_WEIGHT = 0.35
SEMANTIC_WEIGHT = 0.65
LLM_RELEVANCE_WEIGHT = 0.4
EVIDENCE_TERMS = ["experiment", "benchmark", "baseline", "ablation", "evaluate", "dataset", "outperform", "speedup"]
PRACTICAL_TERMS = ["latency", "throughput", "memory", "cost", "speedup", "efficient", "gpu", "serving", "training time", "scalab"]
COMMON_TOKENS = {"the", "and", "for", "with", "from", "that", "this", "language", "model", "models", "llm", "large", "using"}


def _excluded(text: str, topics: list[Topic]) -> bool:
    return any(term.casefold() in text for topic in topics for term in topic.exclude)
```

- [ ] **Step 4: Flip `_recompute` to semantic-primary relevance**

In `src/paper_collector/ranking.py`, replace the relevance block inside `_recompute` (lines 88-93) with:

```python
    keyword_relevance = 100 * max(paper.topic_scores.values(), default=0)
    relevance = keyword_relevance
    if paper.semantic_score is not None:
        relevance = KEYWORD_WEIGHT * keyword_relevance + SEMANTIC_WEIGHT * paper.semantic_score
    if "relevance" in paper.llm_scores:
        relevance = (1 - LLM_RELEVANCE_WEIGHT) * relevance + LLM_RELEVANCE_WEIGHT * paper.llm_scores["relevance"]
```

- [ ] **Step 5: Replace `classify_and_score` with the hybrid gate**

In `src/paper_collector/ranking.py`, replace the entire `classify_and_score` function (lines 112-132) with:

```python
def classify_and_score(
    paper: Paper, topics: list[Topic], anchor_terms: list[str] | None = None,
    keyword_gate: float = MIN_KEYWORD_RELEVANCE, semantic_gate: float = DEFAULT_SEMANTIC_GATE,
) -> Paper:
    """Hybrid relevance gate: a paper passes via the keyword path OR the semantic path.

    The keyword path reproduces the original behavior (anchor term + strong keyword match).
    The semantic path rescues novel-wording papers when an embedding score is available.
    Without embeddings, semantic_score is None and only the keyword path is live.
    """
    text = f"{paper.title} {paper.abstract}".casefold()
    anchors = anchor_terms or DEFAULT_ANCHORS
    seeded = dict(paper.topic_scores)  # semantic fallback topic seeded by add_semantic_scores
    if _excluded(text, topics):
        paper.score = 0.0
        paper.score_reasons = ["命中排除项"]
        return paper
    keyword_topics = _keyword_topics(paper, topics)
    anchor_ok = any(anchor.casefold() in text for anchor in anchors)
    keyword_path = anchor_ok and max(keyword_topics.values(), default=0) >= keyword_gate
    semantic_path = paper.semantic_score is not None and paper.semantic_score >= semantic_gate
    if not (keyword_path or semantic_path):
        paper.score = 0.0
        paper.score_reasons = ["未达关键词或语义相关阈值"]
        return paper
    if keyword_topics:
        paper.topic_scores = keyword_topics
        matched = [topic.title for topic in topics if topic.slug in keyword_topics]
        paper.score_reasons = [f"命中主题：{'、'.join(matched)}"]
    else:
        paper.topic_scores = seeded
        matched = [topic.title for topic in topics if topic.slug in seeded]
        paper.score_reasons = [f"语义相关主题：{'、'.join(matched)}"] if matched else ["语义相关"]
    if paper.venue:
        paper.score_reasons.append(f"已录用至 {paper.venue}")
    if paper.code_url:
        paper.score_reasons.append("附带代码链接")
    _recompute(paper)
    return paper
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_semantic_path_rescues_paper_without_keywords tests.test_ranking.RankingTests.test_paper_with_no_keyword_or_semantic_signal_is_dropped tests.test_ranking.RankingTests.test_exclude_blocks_even_with_semantic_signal tests.test_ranking.RankingTests.test_semantic_score_dominates_relevance -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the whole ranking module to confirm no regressions**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking -v`
Expected: all PASS (existing 8 + new 4). The original tests use no `semantic_score`, so the keyword path matches today's behavior.

- [ ] **Step 8: Commit**

```bash
git add src/paper_collector/ranking.py tests/test_ranking.py
git commit -m "$(cat <<'EOF'
feat: hybrid keyword-or-semantic gate with semantic-primary relevance

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Per-topic semantic seeding in `add_semantic_scores`

**Files:**
- Modify: `src/paper_collector/llm.py`
- Test: `tests/test_llm.py`

So that a paper passing only via the semantic path has a primary topic for diversity selection, `add_semantic_scores` seeds `topic_scores` with its single best-matching topic. `classify_and_score` (Task 2) keeps this seed only when there is no keyword match.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_llm.py` — update imports and add a test:

```python
import os
import unittest
from unittest.mock import patch

from paper_collector.llm import add_semantic_scores, summarize_in_chinese
from paper_collector.models import Paper, Topic


class LlmTests(unittest.TestCase):
    def test_no_key_keeps_papers_local_and_unchanged(self):
        paper = Paper("id", "title", "abstract", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(summarize_in_chinese([paper])[0], paper)
            self.assertIsNone(paper.summary_zh)

    def test_semantic_scores_seed_best_topic(self):
        topics = [Topic("serving", "推理系统", ["kv cache"]), Topic("align", "对齐", ["alignment"])]
        candidate = Paper("p", "title", "abstract", [], "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", [], "", "")
        response = {"data": [
            {"index": 0, "embedding": [1.0, 0.0]},   # topic serving
            {"index": 1, "embedding": [0.0, 1.0]},   # topic align
            {"index": 2, "embedding": [1.0, 0.0]},   # paper -> closest to serving
        ]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_EMBEDDING_MODEL": "m"}, clear=True):
            with patch("paper_collector.llm._post", return_value=response):
                add_semantic_scores([candidate], topics)
        self.assertGreater(candidate.semantic_score, 0)
        self.assertEqual(max(candidate.topic_scores, key=candidate.topic_scores.get), "serving")
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_llm.LlmTests.test_semantic_scores_seed_best_topic -v`
Expected: FAIL — `topic_scores` stays empty because the current `add_semantic_scores` only sets `semantic_score`.

- [ ] **Step 3: Seed the best topic in `add_semantic_scores`**

In `src/paper_collector/llm.py`, replace the final loop of `add_semantic_scores` (lines 39-42) with:

```python
        for paper, vector in zip(papers, paper_vectors, strict=True):
            # Per-topic similarity lets us both score relevance and seed a fallback topic
            # for papers that survive only on semantic similarity (no keyword match).
            sims = [_cosine(vector, topic_vector) for topic_vector in topic_vectors]
            best_index = max(range(len(sims)), key=sims.__getitem__) if sims else 0
            best_similarity = sims[best_index] if sims else 0.0
            mapped = round(max(0.0, min(100.0, (best_similarity - 0.15) / 0.7 * 100)), 1)
            paper.semantic_score = mapped
            if topics:
                paper.topic_scores = {topics[best_index].slug: round(mapped / 100, 4)}
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests.test_llm.LlmTests.test_semantic_scores_seed_best_topic -v`
Expected: PASS. (cosine(paper, serving)=1 → mapped≈100; best topic = serving.)

- [ ] **Step 5: Run the whole LLM module**

Run: `PYTHONPATH=src python3 -m unittest tests.test_llm -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paper_collector/llm.py tests/test_llm.py
git commit -m "$(cat <<'EOF'
feat: seed best-matching topic from per-topic embedding similarity

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Historical novelty + `prepare_candidates` + `rank` refactor

**Files:**
- Modify: `src/paper_collector/ranking.py`
- Test: `tests/test_ranking.py`

`_novelty_scores` learns to compare against recent history; the front of `rank` is extracted into a reusable `prepare_candidates` so `collect.py` can build a score-only shortlist while `rank` keeps its existing contract for tests.

- [ ] **Step 1: Write the failing tests**

Update the ranking import line in `tests/test_ranking.py`:

```python
from paper_collector.ranking import classify_and_score, prepare_candidates, rank, rescore
```

Append to `class RankingTests`:

```python
    def test_history_reduces_novelty(self):
        topic = Topic("serving", "推理系统", ["speculative decoding", "kv cache"])
        twin = paper(paper_id="hist")
        with_history = prepare_candidates([paper(paper_id="n1")], [topic], history_papers=[twin])
        without_history = prepare_candidates([paper(paper_id="n2")], [topic])
        self.assertLess(
            with_history[0].score_breakdown["novelty"],
            without_history[0].score_breakdown["novelty"],
        )

    def test_prepare_candidates_drops_irrelevant(self):
        topic = Topic("serving", "推理系统", ["speculative decoding"])
        off = paper(paper_id="off", title="Database indexing", abstract="B-tree storage.")
        kept = prepare_candidates([paper(paper_id="on"), off], [topic])
        self.assertEqual([p.paper_id for p in kept], ["on"])
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_history_reduces_novelty tests.test_ranking.RankingTests.test_prepare_candidates_drops_irrelevant -v`
Expected: FAIL — `prepare_candidates` does not exist; `_novelty_scores` ignores history.

- [ ] **Step 3: Add history support to `_novelty_scores`**

In `src/paper_collector/ranking.py`, replace the `_novelty_scores` function (lines 64-77) with:

```python
def _novelty_scores(papers: list[Paper], history_papers: list[Paper] | None = None) -> dict[str, float]:
    token_sets = {paper.paper_id: _tokens(f"{paper.title} {paper.abstract}") for paper in papers}
    history_tokens = [_tokens(f"{item.title} {item.abstract}") for item in (history_papers or [])]
    result: dict[str, float] = {}
    for paper in papers:
        own = token_sets[paper.paper_id]
        similarities: list[float] = []
        for other in papers:
            if other.paper_id == paper.paper_id:
                continue
            theirs = token_sets[other.paper_id]
            if own and theirs:
                similarities.append(len(own & theirs) / len(own | theirs))
        for theirs in history_tokens:
            if own and theirs:
                similarities.append(len(own & theirs) / len(own | theirs))
        result[paper.paper_id] = round(_clamp(100 * (1 - 1.5 * max(similarities, default=0)), 25, 100), 1)
    return result
```

- [ ] **Step 4: Extract `prepare_candidates` and refactor `rank`**

In `src/paper_collector/ranking.py`, replace the entire `rank` function (lines 199-209) with both functions below:

```python
def prepare_candidates(
    papers: list[Paper], topics: list[Topic], anchor_terms: list[str] | None = None,
    keyword_gate: float = MIN_KEYWORD_RELEVANCE, semantic_gate: float = DEFAULT_SEMANTIC_GATE,
    history_papers: list[Paper] | None = None,
) -> list[Paper]:
    """Gate, score, and add novelty (same-day + recent history). Returns relevant papers."""
    relevant = [
        paper for paper in papers
        if classify_and_score(paper, topics, anchor_terms, keyword_gate, semantic_gate).score > 0
    ]
    novelty = _novelty_scores(relevant, history_papers)
    for paper in relevant:
        paper.score_breakdown["novelty"] = novelty[paper.paper_id]
    rescore(relevant)
    return relevant


def rank(
    papers: list[Paper], topics: list[Topic], limit: int, anchor_terms: list[str] | None = None,
    shortlist_limit: int = 40, exploration_slots: int = 2,
    keyword_gate: float = MIN_KEYWORD_RELEVANCE, semantic_gate: float = DEFAULT_SEMANTIC_GATE,
    history_papers: list[Paper] | None = None,
) -> list[Paper]:
    pool = prepare_candidates(
        papers, topics, anchor_terms, keyword_gate, semantic_gate, history_papers,
    )
    shortlist = sorted(pool, key=lambda item: item.score, reverse=True)[:shortlist_limit]
    return select_diverse(shortlist, limit, exploration_slots)
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_history_reduces_novelty tests.test_ranking.RankingTests.test_prepare_candidates_drops_irrelevant -v`
Expected: PASS. (Twin history paper → Jaccard 1 → novelty 25; no history single paper → novelty 100.)

- [ ] **Step 6: Run the whole ranking module**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking -v`
Expected: all PASS. `rank` keeps its original signature/behavior, so existing tests stay green.

- [ ] **Step 7: Commit**

```bash
git add src/paper_collector/ranking.py tests/test_ranking.py
git commit -m "$(cat <<'EOF'
feat: penalize novelty against recent history; extract prepare_candidates

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Off-topic cull

**Files:**
- Modify: `src/paper_collector/ranking.py`
- Test: `tests/test_ranking.py`

After LLM assessment, drop papers the LLM rates clearly off-topic — but only assessed papers, and never below `min_keep` (add the highest-scored culled papers back to fill the daily quota).

- [ ] **Step 1: Write the failing tests**

Update the ranking import line in `tests/test_ranking.py`:

```python
from paper_collector.ranking import classify_and_score, cull_off_topic, prepare_candidates, rank, rescore
```

Append to `class RankingTests`:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_cull_drops_assessed_off_topic_paper tests.test_ranking.RankingTests.test_cull_never_drops_below_min_keep tests.test_ranking.RankingTests.test_cull_keeps_unassessed_papers -v`
Expected: FAIL — `cull_off_topic` does not exist.

- [ ] **Step 3: Implement `cull_off_topic`**

In `src/paper_collector/ranking.py`, add this function immediately after `rank` (end of file):

```python
def cull_off_topic(papers: list[Paper], relevance_floor: float, min_keep: int) -> list[Paper]:
    """Drop LLM-judged off-topic papers, preserving order and never going below min_keep.

    Only papers that actually received an LLM relevance score are eligible to be culled.
    If too few survive, the highest-scored culled papers are added back to reach min_keep.
    """
    off_ids = {
        id(paper) for paper in papers
        if "relevance" in paper.llm_scores and paper.llm_scores["relevance"] < relevance_floor
    }
    kept = [paper for paper in papers if id(paper) not in off_ids]
    if len(kept) < min_keep and off_ids:
        culled = sorted((p for p in papers if id(p) in off_ids), key=lambda p: p.score, reverse=True)
        addback_ids = {id(p) for p in culled[: min_keep - len(kept)]}
        off_ids -= addback_ids
        kept = [paper for paper in papers if id(paper) not in off_ids]
    for paper in papers:
        if id(paper) in off_ids:
            paper.score_reasons = list(paper.score_reasons) + ["LLM 判定主题相关度过低"]
    return kept
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking.RankingTests.test_cull_drops_assessed_off_topic_paper tests.test_ranking.RankingTests.test_cull_never_drops_below_min_keep tests.test_ranking.RankingTests.test_cull_keeps_unassessed_papers -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the whole ranking module**

Run: `PYTHONPATH=src python3 -m unittest tests.test_ranking -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paper_collector/ranking.py tests/test_ranking.py
git commit -m "$(cat <<'EOF'
feat: cull LLM-judged off-topic papers with a daily-quota floor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Storage — `load_recent_selected`

**Files:**
- Modify: `src/paper_collector/storage.py`
- Test: `tests/test_storage.py`

Provide the recent-history window the novelty step consumes: every selected paper from daily files in `[run_date - days, run_date)`.

- [ ] **Step 1: Write the failing test**

Update imports in `tests/test_storage.py`:

```python
from paper_collector.storage import (
    canonical_paper_id,
    load_daily_papers,
    load_recent_selected,
    save_daily,
    seen_before,
    update_index,
)
```

Append to `class StorageTests`:

```python
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
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_storage.StorageTests.test_load_recent_selected_respects_window -v`
Expected: FAIL — `load_recent_selected` does not exist (ImportError).

- [ ] **Step 3: Implement `load_recent_selected`**

In `src/paper_collector/storage.py`, update the datetime import (line 6) and add the function after `load_daily_papers` (after line 27):

Change:
```python
from datetime import date, datetime, timezone
```
to:
```python
from datetime import date, datetime, timedelta, timezone
```

Add:
```python
def load_recent_selected(root: Path, run_date: date, days: int) -> list[Paper]:
    """Selected papers from daily files in [run_date - days, run_date), for novelty history."""
    papers: list[Paper] = []
    daily_root = root / "daily"
    if not daily_root.exists() or days <= 0:
        return papers
    cutoff = run_date - timedelta(days=days)
    for path in sorted(daily_root.glob("*.json")):
        try:
            file_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if cutoff <= file_date < run_date:
            papers.extend(load_daily_papers(root, file_date))
    return papers
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `PYTHONPATH=src python3 -m unittest tests.test_storage.StorageTests.test_load_recent_selected_respects_window -v`
Expected: PASS — only `recent` (2026-01-08) falls inside `[2026-01-03, 2026-01-10)`.

- [ ] **Step 5: Run the whole storage module**

Run: `PYTHONPATH=src python3 -m unittest tests.test_storage -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/paper_collector/storage.py tests/test_storage.py
git commit -m "$(cat <<'EOF'
feat: load recently selected papers for novelty history window

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire the new pipeline into `collect.py`

**Files:**
- Modify: `scripts/collect.py`

Assemble the new flow: load history → embed → `prepare_candidates` → score-only shortlist → assess whole shortlist → rescore → cull → diversity pick.

- [ ] **Step 1: Update imports**

In `scripts/collect.py`, replace the two import lines (lines 16-17) with:

```python
from paper_collector.ranking import cull_off_topic, prepare_candidates, rescore, select_diverse
from paper_collector.storage import (
    canonical_paper_id,
    load_daily_papers,
    load_recent_selected,
    save_daily,
    seen_before,
    update_index,
)
```

- [ ] **Step 2: Replace the pipeline body**

In `scripts/collect.py`, replace the block from `add_semantic_scores(papers, settings.topics)` through `update_index(data_root, ranked)` (lines 39-49) with:

```python
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
```

- [ ] **Step 3: Smoke-test the imports and wiring**

Run:
```bash
PYTHONPATH=src python3 -c "import scripts.collect as c; print('collect wired:', bool(c.main))"
```
Expected: `collect wired: True` with no ImportError.

- [ ] **Step 4: Confirm `rank` is no longer referenced in `collect.py`**

Run:
```bash
grep -n "rank(" scripts/collect.py || echo "no direct rank() call — expected"
```
Expected: `no direct rank() call — expected` (the pipeline now uses `prepare_candidates` + `select_diverse`).

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/collect.py
git commit -m "$(cat <<'EOF'
feat: wire collect pipeline to wide LLM filter, cull, and history novelty

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full regression + README note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the entire test suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
Expected: all PASS (test_arxiv, test_build_site, test_llm, test_ranking, test_storage).

- [ ] **Step 2: Update the README behavior list**

In `README.md`, under `## 产品行为`, replace the scoring bullet (the line beginning `- 每日按匹配度、研究质量…`) with:

```markdown
- 每日按匹配度、研究质量、新颖性、实用价值和可信度评分；语义相似度作为主要相关性信号，可召回措辞不同的相关论文，并对与近 14 天已推荐论文高度相似者降权。
- 入围 shortlist 的论文全部进入结构化评审；被判定主题相关度过低者在最终选择前剔除，同时保证每日名额不被掏空。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: describe scoring v3 semantic recall and off-topic cull

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done When

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` is fully green.
- The hybrid gate rescues semantic-only papers and the key-less path reproduces today's behavior.
- The collect pipeline assesses the full ~70-paper shortlist, culls off-topic papers with a daily-quota floor, and penalizes novelty against the recent-history window.
- No `Paper` model field changes, no `site/` changes, no data migration.
