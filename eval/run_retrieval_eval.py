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
  1. All questions must be status="reviewed" — fails closed if any status is missing or "draft".
  2. Resolved commit SHA must exactly match the configured pinned SHA — fails clearly otherwise.
  3. Chunks are produced by the production AST-aware pipeline (parse_repository + generate_repository_chunks).
  4. Embedding generation must succeed completely (status="completed" and count == chunk count).
  5. Retrieval uses the production retrieve_similar_chunks() — no duplicate implementation.
  6. Lexical baseline ranks the SAME production chunks, same query.
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
    from chunker import generate_repository_chunks, SOURCE_CHUNKER_VERSION
    from parser_interface import parse_repository
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
        "generate_repository_chunks": generate_repository_chunks,
        "parse_repository": parse_repository,
        "clone_repository": clone_repository,
    }


# ---------------------------------------------------------------------------
# Score Extraction Helper
# ---------------------------------------------------------------------------

def extract_top1_score(results: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """
    Safely extract top-1 similarity score from production retrieval results list.
    Reads the real result field 'score' (falling back to 'similarity_score').
    Returns None if results list is empty, None, or score field is unavailable/None.
    Raises ValueError if score is an invalid non-numeric type.
    """
    if not results or not isinstance(results, list):
        return None
    first = results[0]
    if not isinstance(first, dict):
        return None
    raw_score = first.get("score") if "score" in first else first.get("similarity_score")
    if raw_score is None:
        return None
    if isinstance(raw_score, (int, float)):
        return float(raw_score)
    raise ValueError(f"Invalid score type in retrieval result: {type(raw_score).__name__} ({raw_score!r})")


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
    """Aggregate metrics across answerable and unanswerable questions."""
    answerable = [r for r in results if not r.get("unanswerable", False)]
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

    latencies = [r["latency_ms"] for r in answerable if "latency_ms" in r and r["latency_ms"] is not None]
    if latencies:
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
    top1_scores = [r["top1_score"] for r in answerable if r.get("top1_score") is not None]
    if top1_scores:
        agg["top1_score_mean"] = sum(top1_scores) / len(top1_scores)
        agg["top1_score_min"] = min(top1_scores)
        agg["top1_score_max"] = max(top1_scores)

        # Answerable hit vs miss top-1 similarity score breakdown
        hit_top1 = [r["top1_score"] for r in answerable if r.get("top1_score") is not None and hit_at_k(r["retrieved_files"], r["expected_files"], 1) == 1]
        miss_top1 = [r["top1_score"] for r in answerable if r.get("top1_score") is not None and hit_at_k(r["retrieved_files"], r["expected_files"], 1) == 0]
        if hit_top1:
            agg["top1_score_hit_mean"] = sum(hit_top1) / len(hit_top1)
        if miss_top1:
            agg["top1_score_miss_mean"] = sum(miss_top1) / len(miss_top1)

    # Unanswerable: top-1 score tracked separately — no recall/MRR
    unanswerable = [r for r in results if r.get("unanswerable", False)]
    if unanswerable:
        agg["unanswerable_count"] = len(unanswerable)
        u_scores = [r["top1_score"] for r in unanswerable if r.get("top1_score") is not None]
        if u_scores:
            agg["unanswerable_top1_score_mean"] = sum(u_scores) / len(u_scores)
            agg["unanswerable_top1_score_min"] = min(u_scores)
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
    SAFETY GATE: Refuse to run if any question status is not explicitly 'reviewed'.
    Fails closed: missing or empty status is treated as unreviewed.
    Smoke mode bypasses this gate (smoke questions have no status field).
    """
    not_reviewed = [
        q["id"] for q in questions
        if q.get("status") != "reviewed"
    ]
    if not_reviewed:
        ids = ", ".join(not_reviewed)
        raise RuntimeError(
            f"SAFETY GATE TRIGGERED: {len(not_reviewed)} question(s) are not status='reviewed'.\n"
            f"Question IDs: {ids}\n"
            "Source review of eval/questions.json is required before running a full evaluation.\n"
            "Mark a question reviewed only after checking its expected files and rationale against the pinned source. "
            "The dataset's reviewed_by field records the reviewer; this dataset was reviewed by an assistant at user request, "
            "not independently audited by a second reviewer."
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
# Build corpus using PRODUCTION AST-aware chunker (parse_repository + generate_repository_chunks)
# ---------------------------------------------------------------------------

def _build_corpus(
    local_path: str,
    commit_sha: str,
    pipe: Dict[str, Any],
    db_url: str,
    repo_url: str,
) -> tuple:
    """
    Build chunk corpus using production AST-aware parse + chunking, embed, persist.
    Returns (run_id, chunks, session).
    """
    parse_results = pipe["parse_repository"](local_path)
    chunks = pipe["generate_repository_chunks"](
        local_path, parse_results, commit_sha=commit_sha
    )

    if not chunks:
        raise RuntimeError(
            f"No source chunks produced for {local_path}. "
            "Check that the directory contains supported source files."
        )

    # Embed using production provider
    provider = pipe["get_embedding_provider"]()
    embeddings, emb_status = pipe["generate_source_embeddings"](
        chunks, repo_url=repo_url, commit_sha=commit_sha, provider=provider
    )

    # SAFETY GATE: Ensure embedding generation succeeded completely
    if emb_status.get("status") != "completed" or len(embeddings) != len(chunks):
        err_msg = emb_status.get("error", "Unknown embedding error")
        raise RuntimeError(
            f"SAFETY GATE TRIGGERED: Embedding generation failed for {local_path}.\n"
            f"  Status:     {emb_status.get('status')}\n"
            f"  Chunks:     {len(chunks)}\n"
            f"  Embeddings: {len(embeddings)}\n"
            f"  Error:      {err_msg}\n"
            "Stopping evaluation runner — embedding generation must succeed before retrieval evaluation."
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

        # SAFETY GATE 1: All questions must be reviewed (fails closed)
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

            # --- Semantic retrieval (production code) ---
            t0 = time.perf_counter()
            sem_result = pipe["retrieve_similar_chunks"](
                session, run_id=run_id, query_text=question_text, top_k=max_k
            )
            sem_latency_ms = (time.perf_counter() - t0) * 1000

            sem_chunks = sem_result.get("results", [])
            sem_files = [r.get("file_path", "") for r in sem_chunks]
            # Extract top-1 score using helper
            top1_score = extract_top1_score(sem_chunks)

            # --- Lexical baseline (SAME corpus, same query, separate timing) ---
            t_lex = time.perf_counter()
            lex_ranked = lexical_rank(question_text, chunks, max_k)
            lex_latency_ms = (time.perf_counter() - t_lex) * 1000
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
                "latency_ms": sem_latency_ms,
                # Lexical baseline (distinct fields & timing)
                "lexical_retrieved_files": lex_files,
                "lexical_latency_ms": lex_latency_ms,
            })

        session.close()

    # Aggregate metrics — semantic
    sem_metrics = compute_metrics(per_question_results, k_values)

    # Aggregate metrics — lexical baseline (distinct: lexical latency, no copied similarity scores)
    lex_results = [
        {
            **r,
            "retrieved_files": r["lexical_retrieved_files"],
            "latency_ms": r.get("lexical_latency_ms", 0.0),
            "top1_score": None,
        }
        for r in per_question_results
    ]
    lex_metrics = compute_metrics(lex_results, k_values)

    # Per-repository breakdown
    per_repo_metrics: Dict[str, Any] = {}
    repo_ids = sorted(list(set(r["repo"] for r in per_question_results)))
    for r_id in repo_ids:
        r_semantic = [r for r in per_question_results if r["repo"] == r_id]
        r_lexical = [
            {
                **r,
                "retrieved_files": r["lexical_retrieved_files"],
                "latency_ms": r.get("lexical_latency_ms", 0.0),
                "top1_score": None,
            }
            for r in r_semantic
        ]
        per_repo_metrics[r_id] = {
            "semantic": compute_metrics(r_semantic, k_values),
            "lexical_baseline": compute_metrics(r_lexical, k_values),
        }

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
        "per_repository": per_repo_metrics,
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
    if "latency_median_ms" in sem:
        lines.append(f"| Latency median ms | {sem['latency_median_ms']:.1f} |")
    if "latency_p95_ms" in sem:
        lines.append(f"| Latency p95 ms | {sem['latency_p95_ms']:.1f} |")

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
    if "latency_median_ms" in lex:
        lines.append(f"| Latency median ms | {lex['latency_median_ms']:.1f} |")
    if "latency_p95_ms" in lex:
        lines.append(f"| Latency p95 ms | {lex['latency_p95_ms']:.1f} |")

    if "per_repository" in result and result["per_repository"]:
        lines += [
            "",
            "## Per-Repository Breakdown",
            "",
        ]
        for r_id, r_dict in result["per_repository"].items():
            r_sem = r_dict.get("semantic", {})
            lines += [
                f"### Repository: `{r_id}`",
                "",
                f"- Answerable count: {r_sem.get('answerable_count', 0)}",
                f"- MRR: {r_sem.get('mrr', 0.0):.3f}",
            ]
            for k in k_values:
                lines.append(f"- recall@{k}: {r_sem.get(f'recall@{k}', 0.0):.3f}")
            lines.append("")

    lines += [
        "> **Warning**: Small dataset (≤20 questions). Metrics have very high variance.",
        "> Test embeddings are deterministic hash-derived and NOT semantic.",
        "> Questions were source-reviewed by an assistant at user request; this is not independent second-reviewer validation.",
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
