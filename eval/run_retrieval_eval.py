"""
Retrieval Evaluation Runner — S24 Part 1.

Usage:
    python -m eval.run_retrieval_eval \\
        --embedding-provider test \\
        --k 1,3,5,10 \\
        [--smoke]

Flags:
    --embedding-provider  Provider name: 'test' or 'sentence-transformers' (default: test)
    --k                   Comma-separated list of k values for recall@k (default: 1,3,5,10)
    --smoke               Smoke-test mode: skips cloning pinned repos; uses a throwaway local
                          fixture. Output goes ONLY to system temp, never to eval/results/.

RULES:
- Does NOT change the production retrieval algorithm.
- Reuses the existing pipeline chunking, embedding, and retrieval code unchanged.
- Lexical baseline lives entirely inside this file (~20 lines, zero new dependencies).
- Output is machine-readable JSON + short markdown summary.
- Results land in eval/results/<timestamp>/ unless --smoke (temp dir only).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from statistics import median, quantiles
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Ensure the repo's pipeline modules are importable when running as
#   python -m eval.run_retrieval_eval
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Lazy imports from the existing pipeline (deferred so sys.path is set first)
# ---------------------------------------------------------------------------

def _import_pipeline() -> Dict[str, Any]:
    """Import pipeline modules — deferred so sys.path is set first."""
    from embeddings import get_embedding_provider, reset_embedding_provider_cache
    from embeddings_stage import generate_source_embeddings
    from db.engine import get_engine, create_all_tables, get_session_factory
    from db.store import persist_analysis, retrieve_similar_chunks
    return {
        "get_embedding_provider": get_embedding_provider,
        "reset_embedding_provider_cache": reset_embedding_provider_cache,
        "generate_source_embeddings": generate_source_embeddings,
        "get_engine": get_engine,
        "create_all_tables": create_all_tables,
        "get_session_factory": get_session_factory,
        "persist_analysis": persist_analysis,
        "retrieve_similar_chunks": retrieve_similar_chunks,
    }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def hit_at_k(retrieved_files: List[str], expected_files: List[str], k: int) -> int:
    """1 if any retrieved file (up to rank k) appears in expected_files, else 0."""
    return int(any(f in expected_files for f in retrieved_files[:k]))


def recall_at_k(retrieved_files: List[str], expected_files: List[str], k: int) -> float:
    """Fraction of expected_files found in top-k retrieved files."""
    if not expected_files:
        return 0.0
    hits = sum(1 for f in expected_files if f in retrieved_files[:k])
    return hits / len(expected_files)


def mrr(retrieved_files: List[str], expected_files: List[str]) -> float:
    """Mean reciprocal rank: 1/rank of first relevant file, or 0 if none found."""
    for rank, f in enumerate(retrieved_files, 1):
        if f in expected_files:
            return 1.0 / rank
    return 0.0


def compute_metrics(
    results: List[Dict[str, Any]], k_values: List[int]
) -> Dict[str, Any]:
    """Aggregate metrics across all answerable questions."""
    answerable = [r for r in results if not r["unanswerable"]]
    if not answerable:
        return {"answerable_count": 0}

    agg: Dict[str, Any] = {"answerable_count": len(answerable)}
    for k in k_values:
        hits = [hit_at_k(r["retrieved_files"], r["expected_files"], k) for r in answerable]
        recalls = [recall_at_k(r["retrieved_files"], r["expected_files"], k) for r in answerable]
        agg[f"hit@{k}"] = sum(hits) / len(hits)
        agg[f"recall@{k}"] = sum(recalls) / len(recalls)

    agg["mrr"] = sum(mrr(r["retrieved_files"], r["expected_files"]) for r in answerable) / len(answerable)

    latencies = [r["latency_ms"] for r in results]
    agg["latency_median_ms"] = median(latencies)
    agg["latency_p95_ms"] = (
        quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    )

    # Breakdown by difficulty
    for diff in ("lookup", "explanation", "cross-file"):
        subset = [r for r in answerable if r.get("difficulty") == diff]
        if subset:
            agg[f"mrr_{diff}"] = (
                sum(mrr(r["retrieved_files"], r["expected_files"]) for r in subset) / len(subset)
            )
            agg[f"count_{diff}"] = len(subset)

    # Breakdown by paraphrase vs non-paraphrase
    for is_para in (True, False):
        subset = [r for r in answerable if r.get("paraphrase") == is_para]
        label = "paraphrase" if is_para else "non_paraphrase"
        if subset:
            agg[f"mrr_{label}"] = (
                sum(mrr(r["retrieved_files"], r["expected_files"]) for r in subset) / len(subset)
            )
            agg[f"count_{label}"] = len(subset)

    # Top-1 similarity score distribution (answerable)
    top1_scores = [r["top1_score"] for r in answerable if r["top1_score"] is not None]
    if top1_scores:
        agg["top1_score_mean"] = sum(top1_scores) / len(top1_scores)
        agg["top1_score_min"] = min(top1_scores)
        agg["top1_score_max"] = max(top1_scores)

    # Unanswerable: top-1 score distribution tracked separately
    unanswerable = [r for r in results if r["unanswerable"]]
    if unanswerable:
        u_scores = [r["top1_score"] for r in unanswerable if r["top1_score"] is not None]
        agg["unanswerable_count"] = len(unanswerable)
        if u_scores:
            agg["unanswerable_top1_score_mean"] = sum(u_scores) / len(u_scores)
            agg["unanswerable_top1_score_max"] = max(u_scores)

    return agg


# ---------------------------------------------------------------------------
# Lexical baseline (~20 lines, no new dependency)
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> List[str]:
    """Whitespace+punctuation split tokeniser."""
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())


def lexical_score(query: str, chunk_text: str) -> float:
    """Token-overlap score: |query_tokens ∩ chunk_tokens| / |query_tokens|."""
    q_tokens = set(_tokenise(query))
    c_tokens = set(_tokenise(chunk_text))
    if not q_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


def lexical_rank(query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """Rank the same chunk dicts by lexical_score descending (deterministic — ties by chunk_id)."""
    scored = [
        (lexical_score(query, c.get("chunk_text", "")), c.get("chunk_id", ""), c)
        for c in chunks
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:top_k]]


# ---------------------------------------------------------------------------
# Build corpus from local path using existing pipeline APIs
# ---------------------------------------------------------------------------

def _build_chunks_from_path(local_path: str) -> List[Dict[str, Any]]:
    """
    Walk a local directory and produce minimal SourceChunk dicts suitable
    for persist_analysis(). Uses the same chunk schema as the pipeline.
    Does NOT call the real AST parser (which requires repo analysis to have
    run first). Produces line-window chunks directly from file text.
    """
    import hashlib

    chunks: List[Dict[str, Any]] = []
    src_path = Path(local_path)
    WINDOW = 30  # lines per chunk

    for ext in (".py", ".js", ".ts", ".mjs"):
        for fpath in sorted(src_path.rglob(f"*{ext}")):
            try:
                rel = str(fpath.relative_to(local_path)).replace("\\", "/")
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for start in range(0, max(1, len(lines)), WINDOW):
                end = min(start + WINDOW, len(lines))
                text = "\n".join(lines[start:end])
                chunk_id = hashlib.sha256(f"{rel}:{start}:{end}:{text}".encode()).hexdigest()[:16]
                lang = {"py": "python", "js": "javascript", "ts": "typescript", "mjs": "javascript"}.get(
                    ext.lstrip("."), "unknown"
                )
                chunks.append({
                    "chunk_id": chunk_id,
                    "file_path": rel,
                    "start_line": start + 1,
                    "end_line": end,
                    "chunk_text": text,
                    "language": lang,
                    "entity_name": None,
                    "entity_type": None,
                    "provenance": "EVAL_LINE_WINDOW",
                    "commit_sha": "smoke",
                })

    return chunks


def _build_corpus(local_path: str, pipe: Dict[str, Any], db_url: str):
    """
    Build chunk corpus, embed, and persist to a fresh SQLite DB.
    Returns (run_id, chunks, session).
    """
    chunks = _build_chunks_from_path(local_path)

    # Generate embeddings using the existing embeddings_stage API
    provider = pipe["get_embedding_provider"]()
    embeddings, _status = pipe["generate_source_embeddings"](
        chunks, repo_url=local_path, commit_sha="smoke", provider=provider
    )

    # Persist to temp DB using the existing store API
    engine = pipe["get_engine"](db_url)
    pipe["create_all_tables"](engine)
    SessionFactory = pipe["get_session_factory"](engine)
    session = SessionFactory()

    result_dict = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": "eval-smoke",
        "chunker_version": "1",
        "embedding_pipeline_version": "1",
        "repository": local_path,
        "repo_url": local_path,
        "commit_sha": "smoke",
        "cache_snapshot_id": f"smoke-{uuid.uuid4().hex[:8]}",
        "cache_key_basis": "local",
        "analyzed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "languages": ["python", "javascript"],
        "analysis_status": "complete",
        "files_analyzed": len(set(c["file_path"] for c in chunks)),
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph_summary": {"total_nodes": 0, "total_edges": 0},
        "knowledge_graph": {"nodes": [], "edges": []},
        "health_score": {"composite_health_score": 75.0, "status": "good"},
        "source_chunks": chunks,
        "source_embeddings": embeddings,
    }

    run_id = pipe["persist_analysis"](session, result_dict)
    session.commit()
    return run_id, chunks, session


# ---------------------------------------------------------------------------
# Core evaluation loop
# ---------------------------------------------------------------------------

def run_evaluation(
    embedding_provider_name: str,
    k_values: List[int],
    smoke: bool,
    output_dir: str,
) -> Dict[str, Any]:
    """Core evaluation loop. Returns full result dict."""

    pipe = _import_pipeline()

    # Set provider env var before importing/caching
    os.environ["EMBEDDING_PROVIDER"] = embedding_provider_name
    pipe["reset_embedding_provider_cache"]()

    max_k = max(k_values)

    if smoke:
        fixture_path = str(_REPO_ROOT / "tests" / "fixtures" / "success_repo")
        questions = [
            {
                "id": "smoke-01",
                "repo": "smoke",
                "question": "What function adds two integers?",
                "expected_files": ["app.py"],
                "difficulty": "lookup",
                "paraphrase": False,
                "unanswerable": False,
                "status": "draft",
            },
            {
                "id": "smoke-02",
                "repo": "smoke",
                "question": "Does this repository implement network retry logic?",
                "expected_files": [],
                "difficulty": "lookup",
                "paraphrase": False,
                "unanswerable": True,
                "status": "draft",
            },
        ]
        repos = [("smoke", fixture_path)]
    else:
        datasets_path = _REPO_ROOT / "eval" / "datasets.json"
        questions_path = _REPO_ROOT / "eval" / "questions.json"
        with open(datasets_path) as f:
            datasets = json.load(f)["repos"]
        with open(questions_path) as f:
            questions = json.load(f)
        repos = [(d["id"], d["url"]) for d in datasets]

    per_question_results: List[Dict[str, Any]] = []

    for repo_id, repo_path_or_url in repos:
        if smoke:
            local_path = repo_path_or_url
        else:
            raise RuntimeError(
                "Non-smoke cloning is not implemented in this runner. "
                "Clone the pinned repos manually and extend _build_corpus to accept a pre-cloned path."
            )

        db_path = os.path.join(output_dir, f"{repo_id}.db")
        db_url = f"sqlite:///{db_path}"

        run_id, chunks, session = _build_corpus(local_path, pipe, db_url)

        repo_questions = [q for q in questions if q["repo"] == repo_id]

        for q in repo_questions:
            question_text = q["question"]
            expected_files = q.get("expected_files", [])
            is_unanswerable = q.get("unanswerable", False)

            # --- Semantic retrieval (existing production code) ---
            t0 = time.perf_counter()
            sem_result = pipe["retrieve_similar_chunks"](
                session, run_id=run_id, query_text=question_text, top_k=max_k
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            sem_chunks = sem_result.get("results", [])
            sem_files = [r.get("file_path", "") for r in sem_chunks]
            top1_score = sem_chunks[0].get("similarity_score") if sem_chunks else None

            # --- Lexical baseline (same chunk list, same query) ---
            lex_ranked = lexical_rank(question_text, chunks, max_k)
            lex_files = [c.get("file_path", "") for c in lex_ranked]

            per_question_results.append({
                "id": q["id"],
                "repo": repo_id,
                "question": question_text,
                "expected_files": expected_files,
                "difficulty": q.get("difficulty"),
                "paraphrase": q.get("paraphrase", False),
                "unanswerable": is_unanswerable,
                # Semantic
                "retrieved_files": sem_files,
                "top1_score": top1_score,
                "latency_ms": latency_ms,
                # Lexical baseline
                "lexical_retrieved_files": lex_files,
            })

        session.close()

    # Aggregate metrics — semantic
    sem_metrics = compute_metrics(per_question_results, k_values)

    # Aggregate metrics — lexical baseline (reuse same result dicts with swapped retrieved_files)
    lex_results = [
        {**r, "retrieved_files": r["lexical_retrieved_files"]}
        for r in per_question_results
    ]
    lex_metrics = compute_metrics(lex_results, k_values)

    return {
        "embedding_provider": embedding_provider_name,
        "k_values": k_values,
        "smoke": smoke,
        "semantic": sem_metrics,
        "lexical_baseline": lex_metrics,
        "per_question": per_question_results,
    }


# ---------------------------------------------------------------------------
# Markdown summary writer
# ---------------------------------------------------------------------------

def write_markdown_summary(result: Dict[str, Any], out_path: str) -> None:
    sem = result["semantic"]
    lex = result["lexical_baseline"]
    k_values = result["k_values"]
    lines = [
        "# Retrieval Evaluation Summary",
        "",
        f"- **Embedding provider**: `{result['embedding_provider']}`",
        f"- **Smoke mode**: {result['smoke']}",
        f"- **Answerable questions**: {sem.get('answerable_count', 0)}",
        f"- **Unanswerable questions**: {sem.get('unanswerable_count', 0)}",
        "",
        "## Semantic Retrieval",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for k in k_values:
        lines.append(f"| recall@{k} | {sem.get(f'recall@{k}', 0.0):.3f} |")
        lines.append(f"| hit@{k} | {sem.get(f'hit@{k}', 0.0):.3f} |")
    lines.append(f"| MRR | {sem.get('mrr', 0.0):.3f} |")
    lines.append(f"| Latency median ms | {sem.get('latency_median_ms', 0.0):.1f} |")
    lines += [
        "",
        "## Lexical Baseline",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for k in k_values:
        lines.append(f"| recall@{k} | {lex.get(f'recall@{k}', 0.0):.3f} |")
    lines.append(f"| MRR | {lex.get('mrr', 0.0):.3f} |")
    lines += [
        "",
        "> **Warning**: Small dataset (≤20 questions). Metrics have very high variance.",
        "> Test embeddings are deterministic hash-derived and NOT semantic.",
        "> Questions are agent-drafted and pending human review.",
        "> File-level hit is a generous metric.",
    ]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieval evaluation harness")
    parser.add_argument(
        "--embedding-provider", default="test",
        help="Embedding provider: 'test' or 'sentence-transformers'",
    )
    parser.add_argument(
        "--k", default="1,3,5,10",
        help="Comma-separated k values for recall@k",
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="Smoke-test mode: use local fixture, output to temp dir only",
    )
    args = parser.parse_args(argv)

    k_values = [int(x.strip()) for x in args.k.split(",")]

    if args.smoke:
        output_dir = tempfile.mkdtemp(prefix="repo_eval_smoke_")
        print(f"[smoke] Output dir: {output_dir}", file=sys.stderr)
    else:
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_dir = str(_REPO_ROOT / "eval" / "results" / ts)
        os.makedirs(output_dir, exist_ok=True)
        print(f"[eval] Output dir: {output_dir}", file=sys.stderr)

    result = run_evaluation(
        embedding_provider_name=args.embedding_provider,
        k_values=k_values,
        smoke=args.smoke,
        output_dir=output_dir,
    )

    # Write outputs
    json_path = os.path.join(output_dir, "results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[eval] JSON results: {json_path}", file=sys.stderr)

    md_path = os.path.join(output_dir, "summary.md")
    write_markdown_summary(result, md_path)
    print(f"[eval] Markdown summary: {md_path}", file=sys.stderr)

    # Brief summary to stdout
    sem = result["semantic"]
    print("\n=== Evaluation complete ===")
    print(f"Provider: {args.embedding_provider}  Smoke: {args.smoke}")
    print(f"Answerable: {sem.get('answerable_count', 0)}  MRR: {sem.get('mrr', 'N/A')}")
    for k in k_values:
        print(f"  recall@{k}: {sem.get(f'recall@{k}', 'N/A')}")


if __name__ == "__main__":
    main()
