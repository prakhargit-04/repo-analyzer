"""
Background Worker for Job Execution (S15).

Processes queued AnalysisJob records asynchronously via a worker thread pool.
Applies stage callbacks to update DB status through each pipeline phase.
"""
from __future__ import annotations
import os
import sys
import traceback
import concurrent.futures
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from main import run_pipeline
from db.engine import get_engine, create_all_tables, get_session_factory
from db.store import (
    get_job_model,
    update_job_stage,
    complete_job,
    fail_job,
    persist_analysis,
    find_completed_run_by_sha,
)


def _sanitize_error_message(exc: Exception) -> str:
    """Sanitize error messages so internal paths and secrets aren't exposed to API clients."""
    msg = str(exc)
    # Remove long absolute file paths if present
    lines = [line for line in msg.splitlines() if not line.strip().startswith("File ")]
    clean = " ".join(lines).strip()
    return clean[:500] if clean else "Analysis execution failed"


def process_job_task(job_id: str, db_url: str, cache_dir: str) -> None:
    """Task worker function that processes a single analysis job by ID.

    Structural invariant:
      - run_pipeline() runs OUTSIDE any DB session to avoid holding a long
        transaction open across network I/O and heavy computation.
      - A fresh short-lived session is opened for each DB write phase so that
        SQLite never sees a stale transaction after a rollback.
      - If the persist+complete phase itself fails, a second safety-net session
        ensures fail_job() is always committed — leaving status="failed" rather
        than the last stage_cb value (e.g. "analyzing").
      - Guaranteed terminal status: top-level try/except Exception catches any
        unhandled error and sets job status="failed" with error_message=str(e).
      - Logging: finally block logs the final job status.
    """
    engine = get_engine(db_url)
    create_all_tables(engine)
    SessionLocal = get_session_factory(engine)

    try:
        # ── Phase 1: Preflight — read job metadata in a short-lived session ──────
        with SessionLocal() as session:
            job = get_job_model(session, job_id)
            if not job or job.status in ("completed", "failed"):
                return
            repo_url = job.repo_url
            commit_sha = job.commit_sha
        # Session is now closed — no long-held lock during pipeline execution.

        # stage_cb always uses its own short-lived session so callbacks never
        # interfere with pipeline or finalization transactions.
        def stage_cb(stage_name: str, stage_status: str, detail: Optional[str] = None):
            with SessionLocal() as cb_session:
                update_job_stage(cb_session, job_id, stage_name, stage_status, detail=detail)
                cb_session.commit()

        # ── Phase 2: Pipeline — runs entirely outside any DB session ─────────────
        pipeline_error: Optional[Exception] = None
        result: Optional[dict] = None
        try:
            result = run_pipeline(
                repo_url=repo_url,
                local_path=None,
                commit_sha=commit_sha,
                cache_dir=cache_dir,
                stage_callback=stage_cb,
                persist_to_db=False,
            )
        except Exception as exc:
            pipeline_error = exc

        # ── Phase 3a: Check for existing completed run (read-only, separate session)
        # Using its own session ensures that no prior read snapshot from find_completed_run_by_sha
        # contaminates the INSERT transaction in Phase 3b (prevents SQLite WAL stale-snapshot
        # UNIQUE constraint violations on Windows and other multi-engine setups).
        cached_run_id: Optional[str] = None
        if result is not None and pipeline_error is None:
            res_sha = result.get("commit_sha") or commit_sha
            if res_sha:
                try:
                    with SessionLocal() as check_session:
                        found = find_completed_run_by_sha(check_session, repo_url, res_sha)
                        if found:
                            cached_run_id = found["run_id"]
                except Exception:
                    pass  # If the check fails, fall through to persist_analysis in 3b.

        # ── Phase 3b: Finalize — fresh write session for persist + complete/fail ──
        try:
            with SessionLocal() as fin_session:
                if pipeline_error is not None:
                    err_msg = _sanitize_error_message(pipeline_error)
                    fail_job(fin_session, job_id, error_message=err_msg)
                    fin_session.commit()
                    return

                # Pipeline succeeded — persist result and complete the job.
                if cached_run_id is not None:
                    run_id = cached_run_id
                    cache_hit = True
                else:
                    run_id = persist_analysis(fin_session, result)
                    cache_hit = False

                analysis_status = result.get("analysis_status", "complete") if result else "failed"
                if analysis_status == "failed":
                    fail_job(fin_session, job_id, error_message=(result.get("error") if result else None) or "Analysis run failed")
                else:
                    job_status = "completed" if analysis_status == "complete" else "partial"
                    complete_job(fin_session, job_id, run_id=run_id, status=job_status, cache_hit=cache_hit)

                fin_session.commit()

        except Exception as fin_exc:
            # Phase 3b itself failed (e.g. persist_analysis threw). Open one more
            # fresh session as a safety net to mark the job failed so it never
            # gets stuck at an intermediate stage name (e.g. "analyzing").
            try:
                with SessionLocal() as safety_session:
                    err_msg = _sanitize_error_message(fin_exc)
                    fail_job(safety_session, job_id, error_message=f"Finalization error: {err_msg}")
                    safety_session.commit()
            except Exception:
                # If even the safety net fails, there is nothing more we can do.
                # The job will remain stuck; log the chain for operator visibility.
                traceback.print_exc()

    except Exception as e:
        try:
            with SessionLocal() as err_session:
                err_msg = _sanitize_error_message(e)
                fail_job(err_session, job_id, error_message=err_msg)
                err_session.commit()
        except Exception:
            traceback.print_exc()
    finally:
        try:
            with SessionLocal() as log_session:
                final_job = get_job_model(log_session, job_id)
                final_status = final_job.status if final_job else "unknown"
                print(f"[worker] Job {job_id} finished with final status: {final_status}", file=sys.stderr)
        except Exception:
            pass




class JobWorkerQueue:
    """Thread pool queue manager for background job processing."""

    def __init__(self, max_workers: int = 2):
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="analysis_worker"
        )

    def submit_job(self, job_id: str, db_url: str, cache_dir: str):
        self.executor.submit(process_job_task, job_id, db_url, cache_dir)

    def shutdown(self, wait: bool = False):
        self.executor.shutdown(wait=wait)


_GLOBAL_WORKER_QUEUE: Optional[JobWorkerQueue] = None


def get_worker_queue() -> JobWorkerQueue:
    global _GLOBAL_WORKER_QUEUE
    if _GLOBAL_WORKER_QUEUE is None:
        _GLOBAL_WORKER_QUEUE = JobWorkerQueue(max_workers=2)
    return _GLOBAL_WORKER_QUEUE
