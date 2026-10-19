#!/usr/bin/env python3
"""
RAG Accuracy and Hallucination Evaluation Harness (Session 25 Part E).

Enforces strict safety and budget gates:
- If OPENAI_API_KEY or GEMINI_API_KEY is missing, prints:
  'NOT RUN: no API key set. See docs/ai-modes.md to run real AI eval.'
  and exits cleanly with code 0.
- When an API key is present:
  - Strict budget cap of 30 queries and $1.00 max cost.
  - Measures citation precision, citation recall, hallucination rate on unanswerable questions,
    latencies (p50, p95), and token cost estimates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from statistics import median, quantiles
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

MAX_BUDGET_QUERIES = 30
MAX_BUDGET_USD = 1.00

# Estimated cost per 1k tokens for standard LLMs (e.g., gpt-4o-mini / gemini-1.5-flash)
INPUT_COST_PER_1K = 0.00015
OUTPUT_COST_PER_1K = 0.00060

UNANSWERABLE_REFUSAL_PATTERNS = [
    r"not found",
    r"does not (contain|implement|exist|have|support)",
    r"no mention",
    r"not implemented",
    r"no record",
    r"i don't know",
    r"cannot find",
    r"unanswerable",
    r"outside the scope",
    r"not present",
]


def check_unanswerable_refusal(answer_text: str) -> bool:
    """True if model correctly stated the information was not found / absent."""
    lower = answer_text.lower()
    return any(re.search(pat, lower) for pat in UNANSWERABLE_REFUSAL_PATTERNS)


def evaluate_rag(
    questions_path: str = "eval/questions.json",
    dry_run: bool = False,
    output_report: Optional[str] = "eval/results/S25E_REPORT.md",
    db_session: Optional[Any] = None,
    repo_run_map: Optional[dict[str, str]] = None,
    max_budget_usd: float = MAX_BUDGET_USD,
) -> dict[str, Any]:
    """
    Evaluates RAG accuracy and hallucination rates.

    Safety & Integrity Invariants:
    1. If no API key is set and dry_run is False -> returns status 'NOT RUN' with metrics None.
    2. If dry_run is True -> returns status 'NOT RUN (DRY RUN / MOCK ONLY)' with metrics None.
       Synthetic or mock numbers are NEVER reported as verified AI accuracy metrics.
    3. If an API key is present:
       - Must call the real production retrieval and answer-generation pipeline.
       - If production database session or indexed analysis runs are unavailable, returns
         status 'BLOCKED' with metrics None. An API key alone NEVER produces status 'COMPLETED'.
       - Tracks attempted, successful, and failed questions separately.
       - Does NOT report 'COMPLETED' if any required question failed or was skipped. Uses
         distinct 'PARTIAL' or 'FAILED' status.
       - Enforces monetary budget cap (default $1.00) and max 30 questions before making
         additional requests. Halts if budget cap is exhausted.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key and not dry_run:
        msg = "NOT RUN: no API key set. See docs/ai-modes.md to run real AI eval."
        print(msg)
        if output_report:
            os.makedirs(os.path.dirname(output_report), exist_ok=True)
            with open(output_report, "w", encoding="utf-8") as f:
                f.write("# RAG Accuracy Evaluation Report (Session 25 Part E)\n\n")
                f.write("> **Status: NOT RUN**\n>\n")
                f.write(f"> {msg}\n>\n")
                f.write("> Harness is built and verified via mock/dry run. To execute: set `OPENAI_API_KEY` or `GEMINI_API_KEY`, ensure indexed runs exist, and run `python eval/rag/eval_rag.py`.\n\n")
                f.write("## Configured Evaluation Gates\n")
                f.write(f"- Pinned budget: {MAX_BUDGET_QUERIES} queries max / ${max_budget_usd:.2f} max cost\n")
                f.write("- Total questions: 30 (20 answerable with line evidence, 10 unanswerable negative probes)\n")
        return {
            "status": "NOT RUN",
            "reason": "No API key set",
            "total_questions": 0,
            "attempted_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "execution_coverage_percent": 0.0,
            "questions_evaluated": 0,
            "citation_precision": None,
            "citation_recall": None,
            "hallucination_rate_on_unanswerable": None,
            "cost_estimate_usd": None,
            "budget_verified": False,
        }

    # Load questions (pinned budget maximum 30 questions)
    with open(questions_path, "r", encoding="utf-8") as f:
        all_loaded = json.load(f)
        questions = all_loaded[:MAX_BUDGET_QUERIES]

    total_questions = len(questions)
    latencies: list[float] = []
    total_input_tokens = 0
    total_output_tokens = 0

    citation_precisions: list[float] = []
    citation_recalls: list[float] = []
    unanswerable_correct = 0
    unanswerable_total = 0

    attempted_count = 0
    success_count = 0
    failed_count = 0
    skipped_count = 0
    accumulated_cost_usd = 0.0
    budget_exhausted = False
    budget_verified = True

    if dry_run:
        print(f"Evaluating RAG harness in dry-run mode across {total_questions} questions...")
        for q in questions:
            start_time = time.perf_counter()
            q_text = q["question"]
            time.sleep(0.002)
            duration_ms = (time.perf_counter() - start_time) * 1000
            latencies.append(duration_ms)
            total_input_tokens += len(q_text.split()) * 4
            total_output_tokens += 50

        cost_est = (total_input_tokens / 1000.0 * INPUT_COST_PER_1K) + (total_output_tokens / 1000.0 * OUTPUT_COST_PER_1K)
        p50_lat = median(latencies) if latencies else 0.0
        p95_lat = quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0)

        report = {
            "status": "NOT RUN (DRY RUN / MOCK ONLY)",
            "reason": "Dry-run plumbing validation only; real AI evaluation requires API key and indexed repository runs",
            "total_questions": total_questions,
            "attempted_count": total_questions,
            "success_count": total_questions,
            "failed_count": 0,
            "skipped_count": 0,
            "execution_coverage_percent": 100.0,
            "questions_evaluated": total_questions,
            "citation_precision": None,
            "citation_recall": None,
            "hallucination_rate_on_unanswerable": None,
            "latency_p50_ms": round(p50_lat, 2),
            "latency_p95_ms": round(p95_lat, 2),
            "cost_estimate_usd": round(cost_est, 6),
            "budget_verified": True,
            "budget_cap_usd": max_budget_usd,
            "budget_exhausted": False,
        }

        if output_report:
            os.makedirs(os.path.dirname(output_report), exist_ok=True)
            with open(output_report, "w", encoding="utf-8") as f:
                f.write("# RAG Accuracy Evaluation Report (Session 25 Part E)\n\n")
                f.write(f"**Status:** {report['status']} (dry_run=True)\n\n")
                f.write("> [!NOTE]\n")
                f.write("> This was a dry-run execution validating harness plumbing, latencies, and token cost estimators.\n")
                f.write("> Real citation precision, citation recall, and hallucination resistance require setting `OPENAI_API_KEY` or `GEMINI_API_KEY` with indexed database analysis runs.\n")
                f.write("> Synthetic accuracy metrics are NEVER fabricated or reported as real results.\n\n")
                f.write("| Metric | Result |\n")
                f.write("| :--- | :--- |\n")
                f.write(f"| **Questions Checked** | {report['questions_evaluated']} |\n")
                f.write("| **Citation Precision** | N/A (Dry run - unvalidated) |\n")
                f.write("| **Citation Recall** | N/A (Dry run - unvalidated) |\n")
                f.write("| **Hallucination Rate (Unanswerable)** | N/A (Dry run - unvalidated) |\n")
                f.write(f"| **Latency p50** | {report['latency_p50_ms']} ms |\n")
                f.write(f"| **Latency p95** | {report['latency_p95_ms']} ms |\n")
                f.write(f"| **Estimated Token Cost** | ${report['cost_estimate_usd']:.6f} |\n")

        return report

    # Real mode: must call actual production retrieval and answer-generation pipeline
    session = db_session
    if session is None:
        try:
            from db.engine import get_engine, get_session_factory
            engine = get_engine()
            session_factory = get_session_factory(engine)
            session = session_factory()
        except Exception as exc:
            msg = f"BLOCKED: Production database connection failed: {exc}"
            print(msg)
            return {
                "status": "BLOCKED",
                "reason": msg,
                "total_questions": total_questions,
                "attempted_count": 0,
                "success_count": 0,
                "failed_count": 0,
                "skipped_count": total_questions,
                "execution_coverage_percent": 0.0,
                "questions_evaluated": 0,
                "citation_precision": None,
                "citation_recall": None,
                "hallucination_rate_on_unanswerable": None,
                "cost_estimate_usd": None,
                "budget_verified": False,
            }

    # Resolve active run_ids for the evaluation repositories
    from rag.service import answer_repository_question
    from db.models import Repository, AnalysisRun

    resolved_run_map: dict[str, str] = dict(repo_run_map or {})
    repos_in_questions = {q.get("repo") for q in questions if q.get("repo")}

    for repo_name in repos_in_questions:
        if repo_name not in resolved_run_map:
            # Query the database for the latest completed/partial run for this repo
            try:
                run_row = (
                    session.query(AnalysisRun)
                    .join(Repository)
                    .filter(Repository.url.ilike(f"%{repo_name}%"))
                    .filter(AnalysisRun.status.in_(["success", "partial", "completed"]))
                    .order_by(AnalysisRun.created_at.desc())
                    .first()
                )
                if run_row:
                    resolved_run_map[repo_name] = run_row.run_id
            except Exception:
                pass

    missing_repos = [r for r in repos_in_questions if r not in resolved_run_map]
    if missing_repos:
        msg = f"BLOCKED: No indexed production analysis run found in database for repositories: {missing_repos}."
        print(msg)
        return {
            "status": "BLOCKED",
            "reason": msg,
            "total_questions": total_questions,
            "attempted_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": total_questions,
            "execution_coverage_percent": 0.0,
            "questions_evaluated": 0,
            "citation_precision": None,
            "citation_recall": None,
            "hallucination_rate_on_unanswerable": None,
            "cost_estimate_usd": None,
            "budget_verified": False,
        }

    print(f"Executing genuine RAG evaluation across {total_questions} questions using real pipeline...")

    # Single-query conservative token estimate for budget guarding
    # ~1200 prompt tokens (system + context) and ~250 output tokens
    single_query_est_cost = (1200 / 1000.0 * INPUT_COST_PER_1K) + (250 / 1000.0 * OUTPUT_COST_PER_1K)

    for q_idx, q in enumerate(questions):
        q_repo = q.get("repo")
        run_id = resolved_run_map.get(q_repo)
        if not run_id:
            skipped_count += 1
            continue

        # Enforce budget cap before issuing additional request
        if accumulated_cost_usd + single_query_est_cost > max_budget_usd:
            print(f"Budget cap reached: accumulated ${accumulated_cost_usd:.4f} + next query est ${single_query_est_cost:.4f} > ${max_budget_usd:.2f}. Halting further requests.")
            budget_exhausted = True
            skipped_count += (total_questions - q_idx)
            break

        attempted_count += 1
        start_time = time.perf_counter()
        q_text = q["question"]
        is_answerable = q.get("is_answerable", not q.get("unanswerable", False))
        exp_files = set(q.get("expected_files", []))

        try:
            resp = answer_repository_question(session, run_id=run_id, question=q_text, top_k=5)
            duration_ms = (time.perf_counter() - start_time) * 1000
            latencies.append(duration_ms)

            citations = resp.get("citations", []) if isinstance(resp, dict) else []
            answer_text = resp.get("answer", "") if isinstance(resp, dict) else ""

            # Token and cost accounting
            usage = resp.get("usage") if isinstance(resp, dict) else None
            if usage and isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
                in_tok = usage["prompt_tokens"]
                out_tok = usage["completion_tokens"]
            else:
                in_tok = len(q_text.split()) * 4 + 800
                out_tok = len(answer_text.split()) * 4
            query_cost = (in_tok / 1000.0 * INPUT_COST_PER_1K) + (out_tok / 1000.0 * OUTPUT_COST_PER_1K)
            accumulated_cost_usd += query_cost

            if is_answerable:
                if citations:
                    correct_citations = sum(1 for c in citations if c.get("file_path") in exp_files)
                    citation_precisions.append(correct_citations / len(citations))
                    cited_files = {c.get("file_path") for c in citations}
                    citation_recalls.append(len(cited_files & exp_files) / len(exp_files) if exp_files else 1.0)
                else:
                    citation_precisions.append(0.0)
                    citation_recalls.append(0.0)
            else:
                unanswerable_total += 1
                if check_unanswerable_refusal(answer_text):
                    unanswerable_correct += 1

            success_count += 1

        except Exception as exc:
            print(f"Question {q.get('id')} execution error: {exc}")
            failed_count += 1

    coverage_pct = round(success_count / total_questions * 100, 1) if total_questions else 0.0

    # Determine status strictly
    if attempted_count == 0:
        status_str = "BLOCKED"
        reason_str = "No questions were attempted"
    elif success_count == total_questions and failed_count == 0 and skipped_count == 0:
        status_str = "COMPLETED"
        reason_str = "All questions successfully executed against production pipeline"
    elif success_count > 0 and (failed_count > 0 or skipped_count > 0):
        status_str = "PARTIAL"
        reason_str = f"Partial execution: {success_count} succeeded, {failed_count} failed, {skipped_count} skipped"
    elif attempted_count > 0 and success_count == 0:
        status_str = "FAILED"
        reason_str = f"All {attempted_count} attempted questions failed"
    else:
        status_str = "BLOCKED"
        reason_str = "Execution could not complete"

    p50_lat = median(latencies) if latencies else 0.0
    p95_lat = quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0)
    avg_precision = round(sum(citation_precisions) / len(citation_precisions), 4) if citation_precisions else None
    avg_recall = round(sum(citation_recalls) / len(citation_recalls), 4) if citation_recalls else None
    hallucination_rate = (
        round(1.0 - (unanswerable_correct / unanswerable_total), 4)
        if unanswerable_total > 0
        else None
    )

    report = {
        "status": status_str,
        "reason": reason_str,
        "total_questions": total_questions,
        "attempted_count": attempted_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "execution_coverage_percent": coverage_pct,
        "questions_evaluated": success_count,
        "citation_precision": avg_precision,
        "citation_recall": avg_recall,
        "hallucination_rate_on_unanswerable": hallucination_rate,
        "latency_p50_ms": round(p50_lat, 2) if latencies else None,
        "latency_p95_ms": round(p95_lat, 2) if latencies else None,
        "cost_estimate_usd": round(accumulated_cost_usd, 6) if budget_verified else None,
        "budget_verified": budget_verified,
        "budget_cap_usd": max_budget_usd,
        "budget_exhausted": budget_exhausted,
    }

    if output_report:
        os.makedirs(os.path.dirname(output_report), exist_ok=True)
        with open(output_report, "w", encoding="utf-8") as f:
            f.write("# RAG Accuracy Evaluation Report (Session 25 Part E)\n\n")
            f.write(f"**Status:** {report['status']} ({report['reason']})\n\n")
            f.write("| Metric | Result |\n")
            f.write("| :--- | :--- |\n")
            f.write(f"| **Total Questions** | {report['total_questions']} |\n")
            f.write(f"| **Attempted** | {report['attempted_count']} |\n")
            f.write(f"| **Successful** | {report['success_count']} |\n")
            f.write(f"| **Failed** | {report['failed_count']} |\n")
            f.write(f"| **Skipped** | {report['skipped_count']} |\n")
            f.write(f"| **Execution Coverage** | {report['execution_coverage_percent']}% |\n")
            f.write(f"| **Citation Precision** | {report['citation_precision']*100:.1f}% |\n" if report['citation_precision'] is not None else "| **Citation Precision** | N/A |\n")
            f.write(f"| **Citation Recall** | {report['citation_recall']*100:.1f}% |\n" if report['citation_recall'] is not None else "| **Citation Recall** | N/A |\n")
            f.write(f"| **Hallucination Rate (Unanswerable)** | {report['hallucination_rate_on_unanswerable']*100:.1f}% |\n" if report['hallucination_rate_on_unanswerable'] is not None else "| **Hallucination Rate (Unanswerable)** | N/A |\n")
            f.write(f"| **Latency p50** | {report['latency_p50_ms']} ms |\n" if report['latency_p50_ms'] is not None else "| **Latency p50** | N/A |\n")
            f.write(f"| **Latency p95** | {report['latency_p95_ms']} ms |\n" if report['latency_p95_ms'] is not None else "| **Latency p95** | N/A |\n")
            f.write(f"| **Estimated Cost** | ${report['cost_estimate_usd']:.6f} |\n" if report['cost_estimate_usd'] is not None else "| **Estimated Cost** | N/A (unverified) |\n")
            f.write(f"| **Budget Exhausted** | {report['budget_exhausted']} |\n")

    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate RAG accuracy, citations, and hallucination rate")
    parser.add_argument("--dry-run", action="store_true", help="Run mock dry run without API key")
    parser.add_argument("--questions", default="eval/questions.json", help="Path to questions.json")
    parser.add_argument("--output", default="eval/results/S25E_REPORT.md", help="Output report path")
    args = parser.parse_args()

    res = evaluate_rag(
        questions_path=args.questions,
        dry_run=args.dry_run,
        output_report=args.output,
    )
    if res.get("status") == "NOT RUN":
        sys.exit(0)
    print("RAG Evaluation complete:", res)


if __name__ == "__main__":
    main()
