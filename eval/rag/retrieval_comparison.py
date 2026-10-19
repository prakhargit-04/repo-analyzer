#!/usr/bin/env python3
"""
Retrieval Metrics Comparison: Vector vs Lexical (BM25 / Word Overlap) Baseline.

Evaluates retrieval quality across questions in eval/questions.json:
- Computes Recall@5 and MRR for Vector vs Lexical search
- Compares score distributions (min, median, p95, max)
- Works offline in test mode (or with real embeddings if configured)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median, quantiles
from typing import Dict, List, Any, Tuple, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from chunker import generate_repository_chunks
from parser_interface import parse_repository
from embeddings import get_embedding_provider


def tokenize(text: str) -> list[str]:
    """Simple alphanumeric lowercasing tokenizer."""
    return [w for w in re.findall(r"\w+", text.lower()) if len(w) > 1]


def compute_bm25_scores(query: str, chunks: list[Any]) -> list[tuple[float, Any]]:
    """Compute BM25 scores for chunks given query."""
    q_tokens = tokenize(query)
    if not q_tokens or not chunks:
        return [(0.0, c) for c in chunks]

    # Precompute corpus stats
    def _chunk_text(ch: Any) -> str:
        return (ch.get("chunk_text", "") if isinstance(ch, dict) else getattr(ch, "chunk_text", "")) or ""

    doc_lens = [len(tokenize(_chunk_text(c))) for c in chunks]
    avgdl = sum(doc_lens) / len(doc_lens) if doc_lens else 1.0
    k1 = 1.5
    b = 0.75

    # Document frequency
    df: Counter[str] = Counter()
    chunk_tfs: list[Counter[str]] = []
    for c in chunks:
        tokens = tokenize(_chunk_text(c))
        tf = Counter(tokens)
        chunk_tfs.append(tf)
        for term in tf:
            df[term] += 1

    n_docs = len(chunks)
    scores: list[tuple[float, Any]] = []
    for idx, c in enumerate(chunks):
        tf = chunk_tfs[idx]
        dlen = doc_lens[idx]
        score = 0.0
        for term in q_tokens:
            if term in tf:
                doc_freq = df[term]
                idf = math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
                freq = tf[term]
                term_score = idf * (freq * (k1 + 1.0)) / (freq + k1 * (1.0 - b + b * (dlen / avgdl)))
                score += term_score
        scores.append((score, c))

    scores.sort(key=lambda x: x[0], reverse=True)
    return scores


def recall_at_k(retrieved_files: list[str], expected_files: list[str], k: int = 5) -> float:
    """Fraction of expected files found in top-k retrieved files."""
    if not expected_files:
        return 0.0
    top_k = retrieved_files[:k]
    hits = sum(1 for ef in expected_files if ef in top_k)
    return hits / len(expected_files)


def mrr(retrieved_files: list[str], expected_files: list[str]) -> float:
    """Mean Reciprocal Rank of first relevant file."""
    for rank, f in enumerate(retrieved_files, 1):
        if f in expected_files:
            return 1.0 / rank
    return 0.0


def score_stats(scores: list[float]) -> dict[str, float]:
    """Calculate min, median, p95, max for non-empty score list."""
    if not scores:
        return {"min": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
    scores_sorted = sorted(scores)
    med = median(scores_sorted)
    p95 = quantiles(scores_sorted, n=20)[18] if len(scores_sorted) >= 20 else max(scores_sorted)
    return {
        "min": round(min(scores_sorted), 4),
        "median": round(med, 4),
        "p95": round(p95, 4),
        "max": round(max(scores_sorted), 4),
    }


def evaluate_retrieval(
    repo_path: str,
    repo_id: str,
    questions_path: str = "eval/questions.json",
    embedding_provider_name: str = "test",
) -> dict[str, Any]:
    """Run vector vs lexical retrieval comparison on questions for repo_id."""
    with open(questions_path, "r", encoding="utf-8") as f:
        questions = json.load(f)

    # Filter answerable questions for this repo
    repo_q = [
        q for q in questions
        if q.get("repo") == repo_id and (q.get("is_answerable") or not q.get("unanswerable"))
    ]

    # Generate real chunks for repository
    parse_results = parse_repository(repo_path)
    chunks = generate_repository_chunks(repo_path, parse_results)
    if not chunks:
        return {"error": "No chunks generated for repo"}

    provider = get_embedding_provider(embedding_provider_name)
    # Pre-embed chunks
    chunk_texts = [c.get("chunk_text", "") if isinstance(c, dict) else getattr(c, "chunk_text", "") for c in chunks]
    chunk_embeds = provider.embed_documents(chunk_texts)

    vector_recalls: list[float] = []
    vector_mrrs: list[float] = []
    vector_scores: list[float] = []

    lexical_recalls: list[float] = []
    lexical_mrrs: list[float] = []
    lexical_scores: list[float] = []

    for q in repo_q:
        q_text = q["question"]
        exp_files = q.get("expected_files", [])

        # 1. Lexical retrieval (BM25)
        bm25_ranked = compute_bm25_scores(q_text, chunks)
        lex_files = []
        for s, c in bm25_ranked:
            f = (c.get("file_path", "") if isinstance(c, dict) else getattr(c, "file_path", "")).replace("\\", "/")
            if f not in lex_files:
                lex_files.append(f)
        if bm25_ranked:
            lexical_scores.append(bm25_ranked[0][0])
        lexical_recalls.append(recall_at_k(lex_files, exp_files, k=5))
        lexical_mrrs.append(mrr(lex_files, exp_files))

        # 2. Vector retrieval (cosine similarity)
        q_embed = provider.embed_query(q_text)
        sims: list[tuple[float, Any]] = []
        for c_idx, c in enumerate(chunks):
            v_embed = chunk_embeds[c_idx]
            dot = sum(a * b for a, b in zip(q_embed, v_embed))
            norm_q = math.sqrt(sum(a * a for a in q_embed)) or 1e-9
            norm_v = math.sqrt(sum(b * b for b in v_embed)) or 1e-9
            sim = dot / (norm_q * norm_v)
            sims.append((sim, c))

        sims.sort(key=lambda x: x[0], reverse=True)
        vec_files = []
        for s, c in sims:
            f = (c.get("file_path", "") if isinstance(c, dict) else getattr(c, "file_path", "")).replace("\\", "/")
            if f not in vec_files:
                vec_files.append(f)
        if sims:
            vector_scores.append(sims[0][0])
        vector_recalls.append(recall_at_k(vec_files, exp_files, k=5))
        vector_mrrs.append(mrr(vec_files, exp_files))

    return {
        "repo": repo_id,
        "question_count": len(repo_q),
        "chunk_count": len(chunks),
        "embedding_provider": embedding_provider_name,
        "vector": {
            "recall@5": round(sum(vector_recalls) / len(vector_recalls) if vector_recalls else 0.0, 4),
            "mrr": round(sum(vector_mrrs) / len(vector_mrrs) if vector_mrrs else 0.0, 4),
            "score_distribution": score_stats(vector_scores),
        },
        "lexical": {
            "recall@5": round(sum(lexical_recalls) / len(lexical_recalls) if lexical_recalls else 0.0, 4),
            "mrr": round(sum(lexical_mrrs) / len(lexical_mrrs) if lexical_mrrs else 0.0, 4),
            "score_distribution": score_stats(lexical_scores),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate Vector vs Lexical (BM25) Retrieval")
    parser.add_argument("--repo-path", default=".cache/repos/iniconfig", help="Path to repository")
    parser.add_argument("--repo-id", default="iniconfig", help="Repository identifier in questions.json")
    parser.add_argument("--provider", default="test", help="Embedding provider (test, sentence_transformers)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    results = evaluate_retrieval(
        repo_path=args.repo_path,
        repo_id=args.repo_id,
        embedding_provider_name=args.provider,
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"=== Retrieval Comparison: Vector vs Lexical (BM25) ===")
        print(f"Repository: {results.get('repo')} (chunks: {results.get('chunk_count')}, questions: {results.get('question_count')})")
        print(f"Embedding Provider: {results.get('embedding_provider')}")
        v = results.get("vector", {})
        l = results.get("lexical", {})
        print(f"\nMetric          Vector ({results.get('embedding_provider')})   Lexical (BM25)")
        print(f"--------------------------------------------------")
        print(f"Recall@5        {v.get('recall@5', 0)*100:6.2f}%                 {l.get('recall@5', 0)*100:6.2f}%")
        print(f"MRR             {v.get('mrr', 0):6.4f}                   {l.get('mrr', 0):6.4f}")
        print(f"\nScore Distributions:")
        print(f"Vector Scores : {v.get('score_distribution')}")
        print(f"Lexical Scores: {l.get('score_distribution')}")


if __name__ == "__main__":
    main()
