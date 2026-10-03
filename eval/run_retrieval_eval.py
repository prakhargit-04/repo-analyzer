"""
Retrieval Evaluation Runner — S24 Part 1.

Usage:
    # Smoke test (harness plumbing validation only — not evidence of semantic retrieval quality):
    python -m eval.run_retrieval_eval --smoke

    # Full evaluation (requires cloned repos at pinned SHAs; run ONLY after human review):
    python -m eval.run_retrieval_eval --embedding-provider test --k 1,3,5,10

Flags:
    --embedding-provider  Provider name: 'test' or 'sentence-transformers' (default: test)
    --k                   Comma-separated k values for recall@k (default: 1,3,5,10)
    --smoke               Smoke-test mode: uses local fixture; output to temp dir only.
                          CLEARLY labelled: harness plumbing validation only.

SAFETY GATES (enforced at runtime):
  1. All questions must be status="reviewed" — refuses to run if any are "draft".
  2. Resolved commit SHA must exactly match the configured pinned SHA — fails clearly otherwise.
  3. Chunks are produced by the production chunker (pipeline/chunker.py chunk_single_file).
  4. Retrieval uses the production retrieve_similar_chunks() — no duplicate implementation.
  5. Lexical baseline ranks the SAME production chunks, same query.

RULES:
- Does NOT change the production retrieval algorithm.
- Reuses existing pipeline chunking, embedding, and retrieval code unchanged.
- Lexical baseline lives entirely inside eval/ (~20 lines, zero new dependencies).
- Results land in eval/results/<timestamp>/ unless --smoke (temp dir only).
"""
from __future__ import annotations

import argparse
import json
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
    from embeddings import get_embedding_provider, reset_embedding_provider_cache, EMBEDDING_PIPELINE_VERSION
    from embeddings_stage import generate_source_embeddings
    from db.engine import get_engine, create_all_tables, get_session_factory
    from db.store import persist_analysis, retrieve_similar_chunks
    from chunker import chunk_single_file, SOURCE_CHUNKER_VERSION
    from clone import clone_repository
    return {
        "get_embedding_provider": get_embedding_provider,
        "reset_embedding_provider_cache": reset_embedding_provider_cache,
        "generate_source_embeddings": generate_source_embeddings,
        "get_engine": get_engine,
        "create_all_tables": create_all_tables,
        "get_session_factory": get_session_factory,
        "persist_analysis": persist_analysis,
        "retrieve_similar_chunks": retrieve_similar_chunks,
        "chunk_single_file": chunk_single_file,
        "clone_repository": clone_repository,
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

    agg["mrr"] = (
        sum(mrr(r["retrieved_files"], r["expected_files"]) for r in answerable)
        / len(answerable)
    )

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
                sum(mrr(r["retrieved_files"], r["expected_files"]) for r in subset)
                / len(subset)
            )
            agg[f"count_{diff}"] = len(subset)

    # Breakdown by paraphrase vs non-paraphrase
    for is_para in (True, False):
        subset = [r for r in answerable if r.get("paraphrase") == is_para]
        label = "paraphrase" if is_para else "non_paraphrase"
        if subset:
            agg[f"mrr_{label}"] = (
                sum(mrr(r["retrieved_files"], r["expected_files"]) for r in subset)
                / len(subset)
            )
            agg[f"count_{label}"] = len(subset)

    # Top-1 similarity score distribution (answerable)
    top1_scores = [r["top1_score"] for r in answerable if r["top1_score"] is not None]
    if top1_scores:
        agg["top1_score_mean"] = sum(top1_scores) / len(top1_scores)
        agg["top1_score_min"] = min(top1_scores)
        agg["top1_score_max"] = max(top1_scores)

    # Unanswerable: top-1 score tracked separately — no recall/MRR
    unanswerable = [r for r in results if r["unanswerable"]]
    if unanswerable:
        agg["unanswerable_count"] = len(unanswerable)
        u_scores = [r["top1_score"] for r in unanswerable if r["top1_score"] is not None]
        if u_scores:
            agg["unanswerable_top1_score_mean"] = sum(u_scores) / len(u_scores)
            agg["unanswerable_top1_score_max"] = max(u_scores)

    return agg


# ---------------------------------------------------------------------------
# Lexical baseline (~20 lines, no new dependency, ranks SAME production chunks)
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
    """Rank SAME production chunk dicts by lexical_score descending (tie-break by chunk_id)."""
    scored = [
        (lexical_score(query, c.get("chunk_text", "")), c.get("chunk_id", ""), c)
        for c in chunks
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:top_k]]


# ---------------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------------

def _check_questions_all_reviewed(questions: List[Dict[str, Any]]) -> None:
    """
    SAFETY GATE: Refuse to run if any question is not status='reviewed'.
    Smoke mode bypasses this gate (smoke questions have no status field).
    """
    not_reviewed = [
        q["id"] for q in questions
        if q.get("status", "reviewed") != "reviewed"
    ]
    if not_reviewed:
        ids = ", ".join(not_reviewed)
        raise RuntimeError(
            f"SAFETY GATE TRIGGERED: {len(not_reviewed)} question(s) are not status='reviewed'.\n"
            f"Question IDs: {ids}\n"
            "Human review of eval/questions.json is required before running a full evaluation.\n"
            "Do NOT mark questions reviewed yourself — that is the human's role."
        )


def _verify_sha(local_path: str, expected_sha: str) -> str:
    """
    SAFETY GATE: Verify that HEAD of the cloned repo exactly matches expected_sha.
    Returns the resolved SHA. Raises RuntimeError if it doesn't match.
    """
    import subprocess
    resolved = subprocess.run(
        ["git", "-C", local_path, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    if resolved != expected_sha:
        raise RuntimeError(
            f"SAFETY GATE TRIGGERED: SHA mismatch.\n"
            f"  Expected: {expected_sha}\n"
            f"  Got:      {resolved}\n"
            f"Refusing to evaluate at an unpinned commit."
        )
    return resolved


# ---------------------------------------------------------------------------
# Build corpus using PRODUCTION chunker (pipeline/chunker.py)
# ---------------------------------------------------------------------------

def _build_chunks_from_local_path(
    local_path: str,
    commit_sha: str,
    chunk_single_file_fn: Any,
) -> List[Dict[str, Any]]:
    """
    Walk local_path and produce source chunks using the PRODUCTION chunker
    (pipeline/chunker.py::chunk_single_file with parse_result=None,
    which triggers the chunker's own line-window fallback).

    This is the same code path the product uses for uncovered lines.
    """
    src_path = Path(local_path)
    all_chunks: List[Dict[str, Any]] = []

    supported_exts = (".py", ".js", ".ts", ".mjs", ".jsx", ".tsx", ".java")
    for ext in supported_exts:
        for fpath in sorted(src_path.rglob(f"*{ext}")):
            try:
                rel = str(fpath.relative_to(local_path)).replace("\\", "/")
            except ValueError:
                continue
            # chunk_single_file with parse_result=None → production line-window chunker
            chunks = chunk_single_file_fn(
                repo_root=local_path,
                rel_path=rel,
                commit_sha=commit_sha,
                parse_result=None,
            )
            all_chunks.extend(c.to_dict() if hasattr(c, "to_dict") else c for c in chunks)

    # Deterministic ordering: file_path then start_line
    all_chunks.sort(key=lambda c: (c.get("file_path", ""), c.get("start_line", 0)))
    return all_chunks


def _build_corpus(
    local_path: str,
    commit_sha: str,
    pipe: Dict[str, Any],
    db_url: str,
    repo_url: str,
) -> tuple:
    """
    Build chunk corpus using production chunker, embed, persist.
    Returns (run_id, chunks, session).
    """
    chunks = _build_chunks_from_local_path(
        local_path, commit_sha, pipe["chunk_single_file"]
    )

    if not chunks:
        raise RuntimeError(
            f"No source chunks produced for {local_path}. "
            "Check that the directory contains supported source files."
        )

    # Embed using production provider
    provider = pipe["get_embedding_provider"]()
    embeddings, _status = pipe["generate_source_embeddings"](
        chunks, repo_url=repo_url, commit_sha=commit_sha, provider=provider
    )

    # Persist using production store API
    engine = pipe["get_engine"](db_url)
    pipe["create_all_tables"](engine)
    SessionFactory = pipe["get_session_factory"](engine)
    session = SessionFactory()

    result_dict = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": "eval-harness",
        "chunker_version": "1",
        "embedding_pipeline_version": "1",
        "repository": repo_url,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "cache_snapshot_id": f"eval-{uuid.uuid4().hex[:8]}",
        "cache_key_basis": "git_sha",
        "analyzed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "languages": ["python", "javascript", "typescript"],
        "analysis_status": "complete",
        "files_analyzed": len(set(c.get("file_path", "") for c in chunks)),
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

    # Set provider env var before caching
    os.environ["EMBEDDING_PROVIDER"] = embedding_provider_name
    pipe["reset_embedding_provider_cache"]()

    max_k = max(k_values)

    if smoke:
        # -----------------------------------------------------------------------
        # SMOKE MODE — harness plumbing validation only.
        # NOT evidence of semantic retrieval quality.
        # Uses local fixture with a synthetic commit SHA (no network needed).
        # Safety gate for question review is bypassed in smoke mode.
        # -----------------------------------------------------------------------
        fixture_path = str(_REPO_ROOT / "tests" / "fixtures" / "success_repo")
        smoke_sha = "0000000000000000000000000000000000000000"
        questions = [
            {
                "id": "smoke-01",
                "repo": "smoke",
                "question": "What function adds two integers?",
                "expected_files": ["app.py"],
                "difficulty": "lookup",
                "paraphrase": False,
                "unanswerable": False,
            },
            {
                "id": "smoke-02",
                "repo": "smoke",
                "question": "Does this repository implement network retry logic?",
                "expected_files": [],
                "difficulty": "lookup",
                "paraphrase": False,
                "unanswerable": True,
            },
        ]
        repos = [("smoke", fixture_path, smoke_sha, fixture_path)]

    else:
        # -----------------------------------------------------------------------
        # FULL EVALUATION MODE — enforces all safety gates.
        # -----------------------------------------------------------------------
        datasets_path = _REPO_ROOT / "eval" / "datasets.json"
        questions_path = _REPO_ROOT / "eval" / "questions.json"
        with open(datasets_path) as f:
            datasets = json.load(f)["repos"]
        with open(questions_path) as f:
            questions = json.load(f)

        # SAFETY GATE 1: All questions must be reviewed
        _check_questions_all_reviewed(questions)

        repos = []
        for d in datasets:
            repos.append((d["id"], d["url"], d["sha"], None))

    per_question_results: List[Dict[str, Any]] = []

    for repo_id, repo_url, pinned_sha, prebuilt_local_path in repos:
        if prebuilt_local_path:
            # Smoke: use pre-existing local path; skip clone and SHA verification
            local_path = prebuilt_local_path
            verified_sha = pinned_sha
        else:
            # Full eval: clone at pinned SHA and verify HEAD exactly
            clone_dest = os.path.join(output_dir, f"clone_{repo_id}")
            print(f"[eval] Cloning {repo_url} @ {pinned_sha} ...", file=sys.stderr)
            resolved = pipe["clone_repository"](repo_url, clone_dest, commit_sha=pinned_sha)
            # SAFETY GATE 2: verify SHA matches exactly
            verified_sha = _verify_sha(clone_dest, pinned_sha)
            print(f"[eval] SHA verified: {verified_sha}", file=sys.stderr)
            local_path = clone_dest

        db_path = os.path.join(output_dir, f"{repo_id}.db")
        db_url = f"sqlite:///{db_path}"

        print(f"[eval] Building corpus for {repo_id} ...", file=sys.stderr)
        run_id, chunks, session = _build_corpus(
            local_path, verified_sha, pipe, db_url, repo_url
        )
        print(f"[eval] Corpus: {len(chunks)} chunks", file=sys.stderr)

        repo_questions = [q for q in questions if q.get("repo") == repo_id]

        for q in repo_questions:
            question_text = q["question"]
            expected_files = q.get("expected_files", [])
            is_unanswerable = q.get("unanswerable", False)

            # --- Semantic retrieval (production code, no reimplementation) ---
            t0 = time.perf_counter()
            sem_result = pipe["retrieve_similar_chunks"](
                session, run_id=run_id, query_text=question_text, top_k=max_k
            )
            latency_ms = (time.perf_counter() - t0) * 1000

            sem_chunks = sem_result.get("results", [])
            sem_files = [r.get("file_path", "") for r in sem_chunks]
            top1_score = sem_chunks[0].get("similarity_score") if sem_chunks else None

            # --- Lexical baseline (SAME corpus, same query, different ranking only) ---
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
                "verified_sha": verified_sha,
                # Semantic
                "retrieved_files": sem_files,
                "top1_score": top1_score,
                "latency_ms": latency_ms,
                # Lexical baseline (same chunks, same query)
                "lexical_retrieved_files": lex_files,
            })

        session.close()

    # Aggregate metrics — semantic
    sem_metrics = compute_metrics(per_question_results, k_values)

    # Aggregate metrics — lexical baseline (swap retrieved_files)
    lex_results = [
        {**r, "retrieved_files": r["lexical_retrieved_files"]}
        for r in per_question_results
    ]
    lex_metrics = compute_metrics(lex_results, k_values)

    return {
        "embedding_provider": embedding_provider_name,
        "k_values": k_values,
        "smoke": smoke,
        "smoke_warning": (
            "HARNESS PLUMBING VALIDATION ONLY — not evidence of semantic retrieval quality."
            if smoke else None
        ),
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
    ]
    if result.get("smoke"):
        lines += [
            "> **SMOKE MODE — Harness plumbing validation only.**",
            "> This is NOT evidence of semantic retrieval quality.",
            "",
        ]
    lines += [
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
        help=(
            "Smoke-test mode: harness plumbing validation only — "
            "NOT evidence of semantic retrieval quality. Output to temp dir only."
        ),
    )
    args = parser.parse_args(argv)

    k_values = [int(x.strip()) for x in args.k.split(",")]

    if args.smoke:
        output_dir = tempfile.mkdtemp(prefix="repo_eval_smoke_")
        print(
            f"[smoke] Output dir: {output_dir}\n"
            "[smoke] HARNESS PLUMBING VALIDATION ONLY — not evidence of semantic retrieval quality.",
            file=sys.stderr,
        )
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

    json_path = os.path.join(output_dir, "results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"[eval] JSON: {json_path}", file=sys.stderr)

    md_path = os.path.join(output_dir, "summary.md")
    write_markdown_summary(result, md_path)
    print(f"[eval] Markdown: {md_path}", file=sys.stderr)

    sem = result["semantic"]
    if args.smoke:
        print("\n=== SMOKE PASS — harness plumbing validation only ===")
    else:
        print("\n=== Evaluation complete ===")
    print(f"Provider: {args.embedding_provider}  Smoke: {args.smoke}")
    print(f"Answerable: {sem.get('answerable_count', 0)}  MRR: {sem.get('mrr', 'N/A')}")
    for k in k_values:
        print(f"  recall@{k}: {sem.get(f'recall@{k}', 'N/A')}")


if __name__ == "__main__":
    main()
