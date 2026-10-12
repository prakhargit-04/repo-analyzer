"""
Unit tests for misc guard functions and background job handling invariants (TASK R6.6).
"""
import os
import unittest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from pipeline.db.engine import create_all_tables
from pipeline.db.models import AnalysisJob
from pipeline.db.store import cleanup_stale_jobs
from pipeline.api.routes import _max_active_jobs, NON_FINAL_JOB_STATUSES


class TestMiscGuards(unittest.TestCase):

    def test_max_active_jobs_parsing(self):
        """Verify _max_active_jobs parses env var correctly and handles invalid inputs safely."""
        old_val = os.environ.get("MAX_ACTIVE_JOBS")
        try:
            # Default fallback when missing
            os.environ.pop("MAX_ACTIVE_JOBS", None)
            self.assertEqual(_max_active_jobs(), 50)

            # Valid integer
            os.environ["MAX_ACTIVE_JOBS"] = "10"
            self.assertEqual(_max_active_jobs(), 10)

            # Non-integer string
            os.environ["MAX_ACTIVE_JOBS"] = "invalid_int"
            self.assertEqual(_max_active_jobs(), 50)

            # Negative integer
            os.environ["MAX_ACTIVE_JOBS"] = "-5"
            self.assertEqual(_max_active_jobs(), 50)
        finally:
            if old_val is not None:
                os.environ["MAX_ACTIVE_JOBS"] = old_val
            else:
                os.environ.pop("MAX_ACTIVE_JOBS", None)

    def test_non_final_job_statuses_consistency(self):
        """Verify NON_FINAL_JOB_STATUSES contains expected non-terminal statuses."""
        expected_statuses = {"queued", "cloning", "parsing", "analyzing", "graph-building", "scoring", "embedding"}
        self.assertEqual(set(NON_FINAL_JOB_STATUSES), expected_statuses)
        # Terminal statuses 'completed' and 'failed' must NOT be in NON_FINAL_JOB_STATUSES
        self.assertNotIn("completed", NON_FINAL_JOB_STATUSES)
        self.assertNotIn("failed", NON_FINAL_JOB_STATUSES)

    def test_cleanup_stale_jobs_only_touches_stale_non_final_jobs(self):
        """Verify cleanup_stale_jobs transitions stuck jobs to failed and leaves completed/recent jobs intact."""
        engine = create_engine("sqlite:///:memory:")
        create_all_tables(engine)

        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=3600)
        recent_time = now - timedelta(seconds=10)

        with Session(engine) as session:
            # 1. Old stuck job in non-final status -> should be marked failed
            job_stale = AnalysisJob(
                id="job_stale_1",
                repo_url="https://github.com/org/repo1",
                status="analyzing",
                created_at=old_time,
                updated_at=old_time,
            )
            # 2. Old job in terminal status 'completed' -> should remain untouched
            job_completed = AnalysisJob(
                id="job_completed_1",
                repo_url="https://github.com/org/repo2",
                status="completed",
                created_at=old_time,
                updated_at=old_time,
            )
            # 3. Old job in terminal status 'failed' -> should remain untouched
            job_failed = AnalysisJob(
                id="job_failed_1",
                repo_url="https://github.com/org/repo3",
                status="failed",
                error_message="Original failure",
                created_at=old_time,
                updated_at=old_time,
            )
            # 4. Recent job in non-final status -> should remain untouched
            job_recent = AnalysisJob(
                id="job_recent_1",
                repo_url="https://github.com/org/repo4",
                status="parsing",
                created_at=recent_time,
                updated_at=recent_time,
            )

            session.add_all([job_stale, job_completed, job_failed, job_recent])
            session.commit()

        # Run cleanup with 1800s threshold
        cleaned_count = cleanup_stale_jobs(engine, stale_seconds=1800)
        self.assertEqual(cleaned_count, 1)

        with Session(engine) as session:
            stale_db = session.query(AnalysisJob).filter_by(id="job_stale_1").one()
            completed_db = session.query(AnalysisJob).filter_by(id="job_completed_1").one()
            failed_db = session.query(AnalysisJob).filter_by(id="job_failed_1").one()
            recent_db = session.query(AnalysisJob).filter_by(id="job_recent_1").one()

            self.assertEqual(stale_db.status, "failed")
            self.assertIn("Job marked failed on startup", stale_db.error_message)

            self.assertEqual(completed_db.status, "completed")
            self.assertEqual(failed_db.status, "failed")
            self.assertEqual(failed_db.error_message, "Original failure")
            self.assertEqual(recent_db.status, "parsing")


if __name__ == "__main__":
    unittest.main()
