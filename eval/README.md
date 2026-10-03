# Retrieval Evaluation Harness

> **Status**: Questions are agent-drafted and pending human review before Part 2 can begin.

---

## How to Run

### Smoke test (no cloning, proof of imports/pipeline/metrics)

```bash
python -m eval.run_retrieval_eval --embedding-provider test --smoke
```

Output goes **only** to a system temp directory. Nothing is written to `eval/results/`.

### Full evaluation (after human review of `eval/questions.json`)

```bash
python -m eval.run_retrieval_eval --embedding-provider test --k 1,3,5,10
```

Results land in `eval/results/<timestamp>/` as `results.json` + `summary.md`.

---

## Dataset Pinning

| Repo | URL | SHA | Language |
|------|-----|-----|----------|
| iniconfig | https://github.com/pytest-dev/iniconfig | `00e7d87c7353b1ffecc4cd55f19acfffedd5233e` | Python |
| qs | https://github.com/ljharb/qs | `07b1d4d82c8f9301c105ea4b94fa2302cfd6e8b4` | JavaScript |

SHAs were resolved with `git ls-remote <url> HEAD` and are not from memory.
Every file listed in `expected_files` was verified to exist at the pinned SHA before questions were written.

---

## Metric Definitions

| Metric | Definition |
|--------|------------|
| **recall@k** | Fraction of `expected_files` that appear in the top-k retrieved chunks. |
| **hit@k** | 1 if any retrieved chunk (rank ≤ k) has its file in `expected_files`, else 0. |
| **MRR** | Mean Reciprocal Rank — `1/rank` of the first relevant file across questions. |
| **latency median/p95** | Wall-clock time from query-vector computation to sorted results. |
| **top-1 similarity** | Cosine similarity score of the highest-ranked chunk. |

All metrics are computed separately for **answerable** questions; unanswerable questions contribute only to the top-1 similarity distribution.

---

## Lexical Baseline

The baseline uses token-overlap scoring on the **same chunk corpus** as semantic retrieval:

```
score(query, chunk) = |tokens(query) ∩ tokens(chunk)| / |tokens(query)|
```

- Tokens: `[a-zA-Z_][a-zA-Z0-9_]*` (lowercase), ~5 lines of code.
- Zero new dependencies.
- Deterministic (ties broken by chunk_id order).
- Lives entirely in `eval/run_retrieval_eval.py`.

---

## Answerable vs Unanswerable Questions

- **Answerable**: `unanswerable: false` — file-level hit = retrieved chunk's file appears in `expected_files`.
  If `expected_line_ranges` are present, line-overlap is reported separately.
- **Unanswerable**: `unanswerable: true` — no recall/MRR computed. Top-1 similarity scores are reported
  as a separate distribution to check whether the retrieval model correctly assigns low confidence.

---

## Limitations

1. **Small dataset (≤20 questions total)**: All metrics have very high variance. Do not draw strong conclusions without a much larger question set.
2. **File-level hit is a generous metric**: A chunk from the right file but wrong function still counts as a hit.
3. **Test embeddings are deterministic hash-derived and NOT semantic**: Results with `--embedding-provider test` measure plumbing only, not retrieval quality.
4. **Questions are agent-drafted and pending human review**: Expected files were selected by reading source files directly — not from retrieval output — but a human must verify correctness before treating eval results as ground truth.
5. **Cloning pinned repos is not implemented in the runner**: Full evaluation requires manual clone of the pinned SHAs before running (non-smoke mode will error with a clear message).

---

## Running Metric Unit Tests

```bash
python -m pytest tests/test_eval_metrics.py -v
```

These tests are offline, no API keys needed, and are collected by default.
