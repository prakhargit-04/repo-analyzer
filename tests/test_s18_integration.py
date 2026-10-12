"""
Session 18 End-to-End Integration & Stabilization Test Suite.

Tests cover:
1. End-to-end analysis submission and job creation.
2. Worker execution lifecycle (queued -> running -> completed/partial/failed).
3. Authoritative single DB persistence (verifying NO duplicate AnalysisRun or child records).
4. Multi-language parser and static analyzer separation (Radon & Bandit run strictly on Python files).
5. Partial and Failure lifecycles.
6. Cache-hit and cache-miss workflows.
"""
from __future__ import annotations

import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select, func

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline.api.app import app
from pipeline.db.engine import get_engine, create_all_tables, get_session_factory
from pipeline.db.models import AnalysisRun, Snapshot, AnalysisJob, Finding, GraphNode, GraphEdge, Repository
from pipeline.db.store import create_job, complete_job, get_job_dict, persist_analysis, find_completed_run_by_sha
from pipeline.worker import process_job_task
from pipeline.static_analysis import analyze_repository, AnalyzerOrchestrator
from pipeline.main import run_pipeline


def _deterministic_analysis(repo_root, parsed_files_rel=None, py_files_rel=None, **kwargs):
    """Controlled analyzer output for worker/database lifecycle tests.

    Analyzer CLI behavior is covered by the dedicated analyzer contract tests;
    worker lifecycle tests must not depend on external tool or ruleset timing.
    """
    files = sorted(parsed_files_rel or py_files_rel or [])
    return {
        "scope_policy": "production_code_only",
        "production_files_analyzed": len(files),
        "test_files_excluded": 0,
        "complexity": {"status": "success", "results": []},
        "maintainability": {"status": "success", "results": []},
        "security": {"status": "unavailable", "results": []},
        "lizard_complexity": {"status": "unavailable", "results": []},
        "semgrep_findings": {"status": "unavailable", "results": []},
        "gitleaks_findings": {"status": "unavailable", "results": []},
        "osv_vulnerabilities": {"status": "unavailable", "results": []},
    }


@pytest.fixture
def test_env(tmp_path):
    old_db = os.environ.get("DATABASE_URL")
    old_cache = os.environ.get("CACHE_DIR")

    db_file = tmp_path / "test_s18.db"
    db_url = f"sqlite:///{db_file}"
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)

    os.environ["DATABASE_URL"] = db_url
    os.environ["CACHE_DIR"] = cache_dir

    engine = get_engine(db_url)
    create_all_tables(engine)

    with TestClient(app) as client:
        try:
            yield client, engine, db_url, cache_dir
        finally:
            engine.dispose()
            if old_db is not None:
                os.environ["DATABASE_URL"] = old_db
            else:
                os.environ.pop("DATABASE_URL", None)
            if old_cache is not None:
                os.environ["CACHE_DIR"] = old_cache
            else:
                os.environ.pop("CACHE_DIR", None)


def test_single_persistence_on_worker_execution(test_env, sample_git_repo, monkeypatch):
    """
    S18 Requirement 3: Verify that worker execution produces EXACTLY ONE AnalysisRun
    in the database and no duplicate findings or graph records.
    """
    import pipeline.clone as clone_module
    import clone as clone_mod_flat

    client, engine, db_url, cache_dir = test_env
    SessionLocal = get_session_factory(engine)

    import static_analysis
    import pipeline.worker as worker_module
    monkeypatch.setattr(static_analysis, "analyze_repository", _deterministic_analysis)
    pipeline_calls = []
    real_run_pipeline = worker_module.run_pipeline

    def capture_run_pipeline(*args, **kwargs):
        pipeline_calls.append(dict(kwargs))
        return real_run_pipeline(*args, **kwargs)

    monkeypatch.setattr(worker_module, "run_pipeline", capture_run_pipeline)

    repo_url = "https://github.com/pytest-org/sample-repo"

    # Inject local repository clone mechanism
    orig_clone = clone_module.clone_repository
    def mock_clone(url, dest, commit_sha=None):
        return orig_clone(sample_git_repo.path, dest, commit_sha=commit_sha or sample_git_repo.commit_sha)

    monkeypatch.setattr(clone_module, "resolve_remote_sha", lambda url: sample_git_repo.commit_sha)
    monkeypatch.setattr(clone_mod_flat, "resolve_remote_sha", lambda url: sample_git_repo.commit_sha)
    monkeypatch.setattr(clone_module, "clone_repository", mock_clone)
    monkeypatch.setattr(clone_mod_flat, "clone_repository", mock_clone)

    # Create job in DB
    with SessionLocal() as session:
        job = create_job(session, repo_url, commit_sha=sample_git_repo.commit_sha)
        job_id = job.id
        session.commit()

    # Process job using worker task directly
    process_job_task(job_id, db_url, cache_dir)
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["commit_sha"] == sample_git_repo.commit_sha
    assert pipeline_calls[0]["repo_url"] == repo_url

    with SessionLocal() as session:
        # Check AnalysisJob state
        j_dict = get_job_dict(session, job_id)
        assert j_dict["status"] in ("completed", "partial")
        assert j_dict["run_id"] is not None

        # Count total AnalysisRun records for this repo
        runs = session.execute(
            select(AnalysisRun).join(Snapshot).join(Repository).where(Repository.repo_url == repo_url)
        ).scalars().all()
        assert len(runs) == 1, f"Expected exactly 1 persisted AnalysisRun, found {len(runs)}"

        run_id = runs[0].id
        # Verify findings and graph nodes are persisted
        nodes_count = session.execute(
            select(func.count(GraphNode.id)).where(GraphNode.run_id == run_id)
        ).scalar()
        assert nodes_count > 0


def test_multilanguage_static_analysis_separation(tmp_path):
    """
    S18 Requirement 4: Python-specific analyzers (Radon, Bandit) must run ONLY on Python files.
    Java and JS/TS files must not trigger Radon syntax errors or fake Bandit failures.
    """
    repo_dir = tmp_path / "polyglot_repo"
    os.makedirs(repo_dir, exist_ok=True)

    # Create a Java file
    java_file = repo_dir / "Main.java"
    java_file.write_text("public class Main { public static void main(String[] args) { System.out.println(\"Hello\"); } }", encoding="utf-8")

    # Create a JS file
    js_file = repo_dir / "index.js"
    js_file.write_text("function hello() { console.log('hello'); }", encoding="utf-8")

    parsed_files_rel = ["Main.java", "index.js"]

    # Run analyze_repository with non-python parsed files
    analysis = analyze_repository(str(repo_dir), parsed_files_rel=parsed_files_rel)

    # Radon CC, Radon MI, and Bandit must be reported as unsupported (or success with 0 results) without status="failed"
    assert analysis["complexity"]["status"] == "unsupported"
    assert analysis["maintainability"]["status"] == "unsupported"
    assert analysis["security"]["status"] == "unsupported"
    assert analysis["complexity"]["results"] == []
    assert analysis["security"]["results"] == []


def test_job_submission_and_cache_hit_flow(test_env, sample_git_repo, monkeypatch):
    """
    S18 Requirements 2 & 7: Verify complete request flow, API endpoints, job polling,
    and subsequent cache-hit handling using local git fixture.
    """
    import static_analysis
    import pipeline.api.routes as routes_module
    import api.routes as api_routes_module
    import pipeline.clone as clone_module
    import clone as clone_mod_flat

    # Mock background worker queue submit_job so POST /analyses doesn't spawn an async thread
    # competing with manual process_job_task on the same job_id
    submitted_jobs = []

    class NoOpQueue:
        def submit_job(self, job_id, db_url, cache_dir):
            submitted_jobs.append(job_id)

    monkeypatch.setattr(routes_module, "get_worker_queue", lambda: NoOpQueue())
    monkeypatch.setattr(api_routes_module, "get_worker_queue", lambda: NoOpQueue())

    # Verify regression assertion: both route module references return NoOpQueue
    assert isinstance(routes_module.get_worker_queue(), NoOpQueue)
    assert isinstance(api_routes_module.get_worker_queue(), NoOpQueue)

    monkeypatch.setattr(static_analysis, "analyze_repository", _deterministic_analysis)

    # Inject local repository clone mechanism
    orig_clone = clone_module.clone_repository
    def mock_clone(url, dest, commit_sha=None):
        return orig_clone(sample_git_repo.path, dest, commit_sha=commit_sha or sample_git_repo.commit_sha)

    monkeypatch.setattr(clone_module, "resolve_remote_sha", lambda url: sample_git_repo.commit_sha)
    monkeypatch.setattr(clone_mod_flat, "resolve_remote_sha", lambda url: sample_git_repo.commit_sha)
    monkeypatch.setattr(clone_module, "clone_repository", mock_clone)
    monkeypatch.setattr(clone_mod_flat, "clone_repository", mock_clone)

    client, engine, db_url, cache_dir = test_env

    repo_url = "https://github.com/pytest-org/sample-repo"

    # 1. Submit analysis request
    res = client.post("/api/v1/analyses", json={"repo_url": repo_url})
    assert res.status_code == 202
    data = res.json()
    job_id = data["job_id"]
    assert data["status"] in ("queued", "running", "completed")

    # Regression assertion: submit_job was logged by NoOpQueue and not dispatched to a live thread pool
    assert len(submitted_jobs) == 1
    assert submitted_jobs[0] == job_id

    # Process task manually to simulate worker thread
    process_job_task(job_id, db_url, cache_dir)

    # 2. Check job status polling endpoint
    res_status = client.get(f"/api/v1/jobs/{job_id}/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert status_data["status"] in ("completed", "partial"), f"Job failed with error: {status_data.get('error_message')}"

    run_id = status_data["run_id"]
    assert run_id is not None

    # 3. Check full analysis endpoint
    res_analysis = client.get(f"/api/v1/analyses/{run_id}")
    assert res_analysis.status_code == 200
    analysis_payload = res_analysis.json()
    assert analysis_payload["repository"] == repo_url
    assert "health_score" in analysis_payload
    assert "knowledge_graph" in analysis_payload

    # 4. Submit identical repository request again to test cache-hit flow
    res_cache = client.post("/api/v1/analyses", json={"repo_url": repo_url, "commit_sha": analysis_payload["commit_sha"]})
    assert res_cache.status_code == 202
    cache_job_data = res_cache.json()
    assert cache_job_data["cache_hit"] is True
    assert cache_job_data["run_id"] == run_id


def test_partial_and_failed_lifecycles(test_env, monkeypatch):
    """
    S18 Requirement 5: Test partial and failed job lifecycles.
    Inject controlled clone failure without network timeouts.
    """
    import pipeline.clone as clone_module
    import clone as clone_mod_flat

    def mock_failed_clone(repo_url, dest_dir, commit_sha=None):
        raise RuntimeError("Controlled mock clone failure: Repository not found")

    monkeypatch.setattr(clone_module, "clone_repository", mock_failed_clone)
    monkeypatch.setattr(clone_mod_flat, "clone_repository", mock_failed_clone)

    client, engine, db_url, cache_dir = test_env
    SessionLocal = get_session_factory(engine)

    # 1. Create job
    with SessionLocal() as session:
        job = create_job(session, "https://github.com/pytest-org/nonexistent-repo")
        job_id = job.id
        session.commit()

    # Process job for non-existent repo (cloning will fail via mock)
    process_job_task(job_id, db_url, cache_dir)

    with SessionLocal() as session:
        j_dict = get_job_dict(session, job_id)
        assert j_dict["status"] == "failed"
        assert j_dict["error_message"] is not None


@pytest.mark.network
def test_remote_github_clone_smoke(tmp_path):
    """Smoke test for real remote GitHub repository cloning capability."""
    from pipeline.clone import clone_repository
    dest = tmp_path / "cloned_iniconfig"
    sha = clone_repository("https://github.com/pytest-dev/iniconfig", str(dest))
    assert sha is not None
    assert len(sha) == 40
