# RAG Accuracy Evaluation Report (Session 25 Part E)

> **Status: NOT RUN**
>
> NOT RUN: No API key in environment. Harness is built and verified via mock/dry run. To execute: set `OPENAI_API_KEY` or `GEMINI_API_KEY` and run `python eval/rag/eval_rag.py`.

## Configured Evaluation Gates
- **Pinned Budget**: 30 queries max / $1.00 max cost
- **Dataset**: 30 questions in `eval/questions.json`
  - 20 Answerable questions with exact file and line-level ground truth evidence across `iniconfig` and `ljharb/qs`.
  - 10 Unanswerable negative probes (non-existent features, wrong libraries, missing endpoints) testing hallucination resistance.
  - Review status: `labeled_by: "assistant"`, `reviewed_by_human: false` (honest provenance).

---

## Retrieval Baseline: Vector (Test Hash) vs Lexical (BM25)

Evaluated via `python eval/rag/retrieval_comparison.py --repo-path .cache/repos/iniconfig --repo-id iniconfig`:

| Metric | Vector (`TestEmbeddingProvider`) | Lexical (`BM25`) |
| :--- | :--- | :--- |
| **Recall@5** | **100.00%** | **100.00%** |
| **MRR** | **0.3700** | **0.7333** |
| **Score Distribution (Min)** | 0.2323 | 5.8048 |
| **Score Distribution (Median)** | 0.3117 | 7.9713 |
| **Score Distribution (p95)** | 0.3787 | 12.5493 |
| **Score Distribution (Max)** | 0.3787 | 12.5493 |

*Note: In default test mode, vectors are generated deterministically via SHA-256 string hashes. The BM25 lexical retriever achieves a higher MRR (0.7333 vs 0.3700) on keyword matching.*

