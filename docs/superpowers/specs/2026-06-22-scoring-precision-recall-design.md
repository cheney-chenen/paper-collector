# Scoring v3 — Precision + Recall via Embedding-Primary Gating and Wide LLM Filtering

**Date:** 2026-06-22
**Status:** Approved (design)
**Component:** `src/paper_collector/ranking.py`, `src/paper_collector/llm.py`, `scripts/collect.py`, `src/paper_collector/config.py`, `topics.toml`

## Goal

Improve the daily selection on **both precision and recall**:

- **Recall** — stop dropping relevant papers that use different wording than the literal topic keywords.
- **Precision** — cut weak / off-topic / repetitive papers from the daily 12.

The radar runs in an environment where the OpenAI-compatible API (embeddings + chat) is **almost always available**, so the design leans on embeddings and the LLM as primary signals while preserving a graceful key-less fallback.

## Root Cause

The current pipeline decides relevance with brittle exact-substring gates **first**, and only lets the strong signals (embeddings, LLM) fine-tune papers that already passed:

- `classify_and_score` (`ranking.py:112`) hard-zeroes any paper that misses an anchor substring or whose max topic-keyword score is `< 0.30`. `semantic_score` is computed for every candidate (`collect.py:39`) but **cannot rescue** a paper that fails the keyword gate → lost recall.
- The shortlist is built with `select_diverse` (topic cap of 4), so a hot topic's good papers are capped out **before** the LLM ever sees them → lost recall.
- The LLM precision filter only covers the top 20 (`llm_assessment_limit`), so anything ranked 21+ by crude heuristics never gets a fair verdict → lost precision.
- Novelty (`_novelty_scores`, `ranking.py:64`) compares only against the **same day's** batch, so a near-duplicate of last week's pick still scores as novel → lost precision.

## Approach: Reorder so strong signals decide membership

### New pipeline flow (`scripts/collect.py`)

```
fetch ~180 → embed all
  → HYBRID GATE: keep if keyword-path OR semantic-path clears bar      (recall)
  → base score (semantic-primary relevance)
  → novelty = same-day + recent-history                               (precision)
  → shortlist = top ~70 by SCORE ONLY (no diversity caps)             (recall)
  → LLM-assess the FULL ~70 shortlist                                 (precision)
  → rescore with LLM signals
  → off-topic cull (drop LLM-judged off-topic, with daily_limit floor)(precision)
  → select_diverse(12, caps + exploration)   ← diversity ONLY here
  → summarize → save
```

Four structural changes vs. today:

1. The gate becomes **hybrid** (keyword OR semantic) instead of hard-substring.
2. The shortlist is ranked by **pure score**, not diversity-capped, so a hot topic's best papers all reach the LLM.
3. The LLM pass covers the **whole widened shortlist** (~70).
4. Diversity constraints apply **only** at the final 12-pick step.

## Detailed Design

### 1. Hybrid relevance gate (recall) — `ranking.py`

Replace the hard gate in `classify_and_score`. A paper passes if it clears **either** path:

- **Keyword path** (preserves today's behavior): anchor term present **and** `max(topic_scores) >= keyword_gate` (default 0.30).
- **Semantic path** (new): `semantic_score >= semantic_gate` (default ~60/100) — rescues novel-wording papers that miss the literal keywords/anchors.

Rules:

- `topic.exclude` terms hard-block **either** path (keeps speech-recognition etc. out).
- **Key-less fallback:** when embeddings are absent, `semantic_score` is `None`, so only the keyword path is live → behavior identical to today.
- **Cost control:** the gate is intentionally generous on recall. The real cost ceiling is the ~70-paper shortlist cap, not the gate; over-admitted papers are ranked down by score and filtered by the LLM pass.

**Supporting change — primary topic for semantic-only papers.** A paper that passes only via the semantic path has empty `topic_scores`, which would break `_primary_topic` (`ranking.py:147` calls `max()` on an empty dict) and thus `select_diverse`. `add_semantic_scores` (`llm.py:27`) will be extended to compute **per-topic** similarity and assign the best-matching topic as a fallback `topic_scores` entry. Every surviving paper then has a primary topic. The fallback entry is only written when the keyword path produced no topic for that paper, so keyword-derived topic scores are never overwritten.

### 2. Relevance reweighting (precision + recall) — `_recompute` in `ranking.py`

Flip embeddings to the primary relevance signal:

- Today: `relevance = 0.6·keyword + 0.4·semantic`, then `0.7·blend + 0.3·llm`.
- New: `relevance = 0.35·keyword + 0.65·semantic` (semantic-primary, keyword as booster), then `0.6·blend + 0.4·llm_relevance` (LLM weighted higher as the precision arbiter).

When `semantic_score` is `None`, relevance falls back to keyword only (as today). When no LLM relevance exists, the blend step is skipped (as today).

The blend weights (`0.35` / `0.65` / `0.4`) are named **module constants** in `ranking.py`, not config — keeping the config surface to the knobs that change cost/behavior (YAGNI).

### 3. Wide LLM precision filter — `collect.py` + `ranking.py`

- Raise `shortlist_limit` 40 → 70 and `llm_assessment_limit` 20 → 70 so the entire widened shortlist gets an LLM verdict.
- Split today's `rank()`: it currently returns a `select_diverse` shortlist (topic caps). It will instead return the **top-N by pure score** (no diversity caps). `select_diverse` moves to the final 12-pick only. `assess_papers` then covers the full shortlist.

### 4. Off-topic cull (precision) — `ranking.py` + `collect.py`

After assessment + rescore, drop papers the LLM rates clearly off-topic:

- Condition: `llm_scores["relevance"] < relevance_floor` (default ~30).
- **Guard 1:** only acts on papers that actually received LLM scores (assessed ones); heuristic-only papers are never culled on this basis.
- **Guard 2:** if fewer than `daily_limit` papers survive, the highest-scored culled papers are added back, so the daily 12 always fills.
- Explainable: culled papers carry a reason such as `"LLM 判定主题相关度过低"`.

### 5. Historical novelty (precision) — `ranking.py` + `collect.py`

Extend `_novelty_scores` to compare each candidate against recently **selected** papers, not just the same-day batch:

- **Source:** selected papers from the last `history_days` (~14) of daily files, loaded in `collect.py` and passed into the novelty step as a new optional `history_papers` argument. (Daily files are used rather than the cumulative `index.json` so the window emphasizes recent saturation and stays bounded.)
- **Mechanic:** reuse `_tokens` + Jaccard. Novelty is penalized by the **max similarity across both the same-day batch and recent history**: `novelty = clamp(100 · (1 − 1.5 · max_sim), 25, 100)`.
- Pure-Python, no API calls; cost is trivial (~hundreds of recent papers × ~70 candidates) and fully key-less-safe.

### 6. Configuration — `config.py` + `topics.toml`

New / promoted keys in `[collector]`, all backward-compatible via `.get()` defaults in `load_settings`:

| key | from → to | purpose |
|---|---|---|
| `shortlist_limit` | 40 → 70 | wider LLM coverage |
| `llm_assessment_limit` | 20 → 70 | assess the whole shortlist |
| `keyword_gate` | hardcoded `MIN_KEYWORD_RELEVANCE` 0.30 → config | keyword-path threshold |
| `semantic_gate` | new, ~60.0 | semantic-path rescue threshold |
| `relevance_floor` | new, ~30.0 | off-topic cull cutoff |
| `history_days` | new, ~14 | historical-novelty window |

`Settings` (`config.py:11`) gains the four new fields with defaults.

## Error Handling

No new failure surface. `llm.py` already wraps every API call in try/except and returns gracefully on failure. On a bad API day the system degrades to today's heuristic behavior rather than failing the run:

- Hybrid gate → keyword path only.
- Relevance reweighting → keyword-only relevance.
- Off-topic cull → no-op (no papers have LLM scores).
- Historical novelty → unaffected (no external calls).

The run never overwrites an existing daily report on failure (existing behavior, unchanged).

## Scope Boundaries (Non-Goals)

- **No feedback / personalization.** The dead `personal_score` loop (declared with weight 5 but never populated; browser feedback in `site/app.js:82` stays local) is left untouched — not revived, not removed.
- **No `Paper` model changes, no data migration.** Everything reuses existing fields (`score_breakdown`, `llm_scores`, `score_reasons`, `topic_scores`, `semantic_score`).
- **No `site/` changes.** The dashboard and stored daily/index JSON keep working unchanged.

## Testing

Extend the existing `unittest` suite, written test-first:

- **`test_ranking.py`**
  - Semantic-only paper (no keyword hit, high `semantic_score`) passes the gate **and** receives a primary topic — `select_diverse` does not crash.
  - Paper with neither keyword nor semantic signal fails the gate.
  - `topic.exclude` term blocks a paper that would otherwise pass either path.
  - Relevance reweighting: a paper with high `semantic_score` and weak keywords scores higher relevance than under the old 0.6/0.4 blend.
  - Historical novelty: a candidate near-identical to a `history_papers` entry gets low novelty; a dissimilar candidate gets high novelty.
  - Off-topic cull: a paper with `llm_scores["relevance"]` below `relevance_floor` is dropped; when too few survive, the floor adds the highest-scored culled papers back to reach `daily_limit`.
- **`test_llm.py`**
  - `add_semantic_scores` (mocked API) records a per-topic best-topic fallback assignment and does not overwrite keyword-derived topic scores.
- **Regression**
  - The key-less path (no `OPENAI_API_KEY`) reproduces today's gating/scoring behavior.
  - All existing tests stay green.

## Affected Files

- `src/paper_collector/ranking.py` — hybrid gate, relevance reweighting, off-topic cull, historical novelty, `rank()` split.
- `src/paper_collector/llm.py` — per-topic similarity + fallback topic assignment in `add_semantic_scores`.
- `src/paper_collector/config.py` — new `Settings` fields and `load_settings` defaults.
- `scripts/collect.py` — new flow (score-only shortlist, full-shortlist assessment, history loading, cull step).
- `topics.toml` — new/updated `[collector]` keys.
- `tests/test_ranking.py`, `tests/test_llm.py` — new and updated tests.
