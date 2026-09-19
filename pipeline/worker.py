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
    """Task worker function that processes a single analysis job by ID."""
    engine = get_engine(db_url)
    create_all_tables(engine)
    SessionLocal = get_session_factory(engine)

    with SessionLocal() as session:
        job = get_job_model(session, job_id)
        if not job or job.status in ("completed", "failed"):
            return

        def stage_cb(stage_name: str, stage_status: str, detail: Optional[str] = None):
            with SessionLocal() as cb_session:
                update_job_stage(cb_session, job_id, stage_name, stage_status, detail=detail)
                cb_session.commit()

        try:
            repo_url = job.repo_url
            commit_sha = job.commit_sha

            # Run pipeline orchestrator
            result = run_pipeline(
                repo_url=repo_url,
                local_path=None,
                commit_sha=commit_sha,
                cache_dir=cache_dir,
                stage_callback=stage_cb,
            )

            # Persist to database
            run_id = persist_analysis(session, result)
            job_status = "completed" if result.get("analysis_status") == "complete" else "partial"
            complete_job(session, job_id, run_id=run_id, status=job_status, cache_hit=False)
            session.commit()

        except Exception as exc:
            session.rollback()
            err_msg = _sanitize_error_message(exc)
            fail_job(session, job_id, error_message=err_msg)
            session.commit()


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
