# Retrieval Evaluation Harness

> **Status**: All 20 questions were source-reviewed against the pinned revisions at the user's request. Each entry records `status: "reviewed"` and `reviewed_by: "assistant-source-review"`. This is not independent second-reviewer validation; treat results as exploratory and inspect `eval/REVIEW_LOG.md` before relying on them.

---

## How to Run

### Smoke test (no external network needed, proof of imports/pipeline/metrics)

```bash
python -m eval.run_retrieval_eval --embedding-provider test --smoke
```

Output goes **only** to a system temp directory. Nothing is written to `eval/results/`.

### Full evaluation (after source review of `eval/questions.json`)

```bash
python -m eval.run_retrieval_eval --embedding-provider test --k 1,3,5,10
```

Full evaluation automatically clones pinned repository SHAs via the production `clone_repository()` function, verifies commit SHA equality via `_verify_sha()`, builds the corpus using AST-aware `parse_repository()` and `generate_repository_chunks()`, generates embeddings, and writes results to `eval/results/<timestamp>/` as `results.json` + `summary.md`.

---

## Dataset Pinning

| Repo | URL | SHA | Language |
|------|-----|-----|----------|
| iniconfig | https://github.com/pytest-dev/iniconfig | `00e7d87c7353b1ffecc4cd55f19acfffedd5233e` | Python |
| qs | https://github.com/ljharb/qs | `07b1d4d82c8f9301c105ea4b94fa2302cfd6e8b4` | JavaScript |

SHAs were resolved with `git ls-remote <url> HEAD` and are pinned explicitly.
Every file listed in `expected_files` was verified to exist at the pinned SHA before questions were written.

---

## Metric Definitions

| Metric | Definition |
|--------|------------|
| **recall@k** | Fraction of `expected_files` that appear in the top-k retrieved chunks. |
| **hit@k** | 1 if any retrieved chunk (rank ≤ k) has its file in `expected_files`, else 0. |
| **MRR** | Mean Reciprocal Rank — `1/rank` of the first relevant file across questions. |
| **latency median/p95** | Wall-clock time from query retrieval invocation to sorted results. |
| **top-1 similarity** | Cosine similarity score extracted from the `score` field of the highest-ranked chunk. |
| **top-1 hit/miss mean** | Mean top-1 similarity score broken down by hit@1 == 1 vs hit@1 == 0 for answerable questions. |

All metrics are computed separately for **answerable** questions; unanswerable questions contribute only to the unanswerable top-1 similarity score distribution.

---

## Lexical Baseline

The baseline uses token-overlap scoring on the **same AST-derived production chunk corpus** as semantic retrieval:

```
score(query, chunk) = |tokens(query) ∩ tokens(chunk)| / |tokens(query)|
```

- Tokens: `[a-zA-Z_][a-zA-Z0-9_]*` (lowercase), ~5 lines of code.
- Zero new dependencies.
- Distinct JSON metric section: uses separate lexical timing (`lexical_latency_ms`) and never copies semantic similarity scores or latencies.
- Deterministic (ties broken by chunk_id order).
- Lives entirely in `eval/run_retrieval_eval.py`.

---

## Answerable vs Unanswerable Questions

- **Answerable**: `unanswerable: false` — file-level hit = retrieved chunk's file appears in `expected_files`. Evaluation is currently file-level; `expected_line_ranges` are `null` across draft questions.
- **Unanswerable**: `unanswerable: true` — no recall/MRR computed. Top-1 similarity scores are reported as a separate distribution (`unanswerable_top1_score_mean`, `min`, `max`) to check whether the retrieval model assigns lower similarity to unanswerable queries.

---

## Source Review Log

The initial draft labels and expected paths were reviewed against the exact pinned source revisions. The detailed question-by-question record is in [`REVIEW_LOG.md`](REVIEW_LOG.md). In particular:

- Identifier-containing questions (`ini-02`, `ini-04`, `qs-02`, `qs-03`, `ini-06`, `ini-09`) are labelled as non-paraphrases.
- Questions that avoid the relevant source identifiers are labelled as paraphrases where that distinction applies.
- `ini-10` includes both the duplicate-section implementation (`src/iniconfig/_parse.py`) and the exception definition (`src/iniconfig/exceptions.py`).
- The three unanswerable questions are deliberately about features outside the pinned projects; they are evaluated by their top-1 score distribution rather than recall/MRR.

The review was performed by an AI assistant at the user's explicit request, not by an independent human reviewer. Keep this limitation attached to any results derived from the dataset.

---

## Limitations

1. **Small dataset (20 questions total)**: All metrics have high variance.
2. **File-level hit is a generous metric**: A chunk from the right file but wrong function counts as a hit.
3. **Test embeddings are deterministic hash-derived and NOT semantic**: Results with `--embedding-provider test` measure harness plumbing only, not retrieval quality.
4. **Review independence**: Questions are source-reviewed and marked `status: "reviewed"` by an assistant at the user's request. This is not independent human review; labels may still contain judgement errors. See `eval/REVIEW_LOG.md`.

---

## Running Metric Unit Tests

```bash
python -m pytest tests/test_eval_metrics.py -v
```

These tests are offline, no API keys needed, and run deterministically.
