"""
Integration test suite for FastAPI backend and job system (S15).
"""
from __future__ import annotations
import os
import sys
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline.api.app import app
from pipeline.db.engine import get_engine, create_all_tables
from pipeline.db.store import (
    persist_analysis,
    create_job,
    complete_job,
    get_job_dict,
)


@pytest.fixture
def temp_db_and_client(tmp_path):
    old_db = os.environ.get("DATABASE_URL")
    old_cache = os.environ.get("CACHE_DIR")

    db_file = tmp_path / "test_api.db"
    db_url = f"sqlite:///{db_file}"
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)

    os.environ["DATABASE_URL"] = db_url
    os.environ["CACHE_DIR"] = cache_dir

    engine = get_engine(db_url)
    create_all_tables(engine)

    with TestClient(app) as client:
        try:
            yield client, engine, cache_dir
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


def test_health_and_readiness_endpoints(temp_db_and_client):
    client, _, _ = temp_db_and_client

    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"
    assert "version" in res_health.json()

    res_ready = client.get("/api/v1/readiness")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"
    assert res_ready.json()["database"] == "connected"


def test_submit_analysis_validation_rejects_local_paths(temp_db_and_client):
    client, _, _ = temp_db_and_client

    # Local file path must be explicitly rejected (S22: 422 from GitHub-HTTPS-only validator)
    # validate_github_url rejects non-https scheme with a message containing "HTTPS"
    res = client.post("/api/v1/analyses", json={"repo_url": "/tmp/local_repo"})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "HTTPS" in detail, f"Expected 'HTTPS' in rejection detail, got: {detail!r}"

    # Unsafe flag injection attempt rejected
    res_unsafe = client.post("/api/v1/analyses", json={"repo_url": "-oProxyCommand=touch /tmp/pwned"})
    assert res_unsafe.status_code == 422

    # Non-GitHub host rejected
    res_gitlab = client.post("/api/v1/analyses", json={"repo_url": "https://gitlab.com/user/repo"})
    assert res_gitlab.status_code == 422

    # HTTP (non-HTTPS) rejected
    res_http = client.post("/api/v1/analyses", json={"repo_url": "http://github.com/user/repo"})
    assert res_http.status_code == 422


def test_job_submission_and_retrieval(temp_db_and_client):
    client, engine, _ = temp_db_and_client

    test_url = "https://github.com/pytest-dev/iniconfig"

    # Pre-populate an analysis run for iniconfig to test API retrieval
    from pipeline.db.engine import get_session_factory
    SessionLocal = get_session_factory(engine)

    canonical_data = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v1.0.0",
        "analyzer_version": "0.15.0",
        "repository": test_url,
        "commit_sha": "00e7d87c7353b1ffecc4cd55f19acfffedd5233e",
        "cache_snapshot_id": "00e7d87c7353b1ffecc4cd55f19acfffedd5233e",
        "cache_key_basis": "git_sha",
        "analyzed_at_utc": "2026-09-19T22:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 2,
        "parse_errors": [],
        "static_analysis": {
            "bandit": {"status": "success", "results": [{"rule_id": "B101", "issue_severity": "LOW", "filename": "src/ini.py", "line_number": 10, "issue_text": "Use of assert"}], "errors": []}
        },
        "knowledge_graph_summary": {"nodes": 3, "edges": 1},
        "knowledge_graph": {
            "nodes": [
                {"id": "src/ini.py", "type": "file", "name": "src/ini.py", "file": "src/ini.py"},
                {"id": "src/ini.py::ParseError", "type": "class", "name": "ParseError", "file": "src/ini.py", "start_line": 5, "end_line": 15},
                {"id": "finding::bandit::B101::10", "type": "finding", "analyzer": "bandit", "rule_id": "B101", "severity": "LOW", "file": "src/ini.py", "line": 10, "message": "Use of assert"}
            ],
            "edges": [
                {"source": "src/ini.py", "target": "src/ini.py::ParseError", "relation": "defines", "confidence": "high", "provenance": "parser"}
            ]
        },
        "health_score": {
            "composite_health_score": 85.5,
            "status": "complete",
            "sub_scores": {"code_quality": 90.0, "security": 81.0},
            "component_statuses": {"radon_mi": "success", "bandit": "success"},
            "weights_used": {"radon_mi": 0.5, "bandit": 0.5},
            "weights_renormalized": False,
            "missing_components": [],
            "formula": "v2",
            "scope_policy": "strict"
        }
    }

    with SessionLocal() as session:
        run_id = persist_analysis(session, canonical_data)
        session.commit()

    # 1. Fetch full analysis via API
    res_run = client.get(f"/api/v1/analyses/{run_id}")
    assert res_run.status_code == 200
    ret_run = res_run.json()
    assert ret_run["repository"] == test_url
    assert ret_run["commit_sha"] == "00e7d87c7353b1ffecc4cd55f19acfffedd5233e"
    assert ret_run["files_analyzed"] == 2
    assert ret_run["health_score"]["composite_health_score"] == 85.5

    # 2. Fetch run status summary
    res_status = client.get(f"/api/v1/analyses/{run_id}/status")
    assert res_status.status_code == 200
    assert res_status.json()["analysis_status"] == "complete"

    # 3. Fetch summary endpoint
    res_sum = client.get(f"/api/v1/analyses/{run_id}/summary")
    assert res_sum.status_code == 200
    assert res_sum.json()["health_score"]["composite_health_score"] == 85.5

    # 4. Fetch graph endpoint with filtering
    res_graph = client.get(f"/api/v1/analyses/{run_id}/graph?node_type=class")
    assert res_graph.status_code == 200
    graph_data = res_graph.json()
    assert len(graph_data["nodes"]) == 1
    assert graph_data["nodes"][0]["name"] == "ParseError"

    # 5. Fetch findings endpoint
    res_findings = client.get(f"/api/v1/analyses/{run_id}/findings?analyzer=bandit")
    assert res_findings.status_code == 200
    findings_data = res_findings.json()
    assert len(findings_data["findings"]) == 1
    assert findings_data["findings"][0]["rule_id"] == "B101"

    # 6. Fetch files list endpoint
    res_files = client.get(f"/api/v1/analyses/{run_id}/files")
    assert res_files.status_code == 200
    assert len(res_files.json()["files"]) == 1

    # 7. Fetch file detail endpoint
    res_file_detail = client.get(f"/api/v1/analyses/{run_id}/files/src/ini.py")
    assert res_file_detail.status_code == 200
    assert res_file_detail.json()["language"] == "python"
    assert len(res_file_detail.json()["entities"]) == 3


    # 8. Fetch repository runs history (with canonical URL, uppercase host, .git, and trailing slash)
    for variant in [test_url, "https://GITHUB.COM/pytest-dev/iniconfig", "https://github.com/pytest-dev/iniconfig.git", "https://github.com/pytest-dev/iniconfig/"]:
        res_runs = client.get(f"/api/v1/repositories/runs?repo_url={variant}")
        assert res_runs.status_code == 200
        assert res_runs.json()["total_runs"] == 1

    # 9. Fetch latest repository analysis (with canonical URL, uppercase host, .git, and trailing slash)
    for variant in [test_url, "https://GITHUB.COM/pytest-dev/iniconfig", "https://github.com/pytest-dev/iniconfig.git", "https://github.com/pytest-dev/iniconfig/"]:
        res_latest = client.get(f"/api/v1/analyses/latest?repo_url={variant}")
        assert res_latest.status_code == 200
        assert res_latest.json()["run_id"] == run_id



def test_cache_hit_short_circuit(temp_db_and_client):
    client, engine, _ = temp_db_and_client
    test_url = "https://github.com/pytest-dev/iniconfig"
    test_sha = "00e7d87c7353b1ffecc4cd55f19acfffedd5233e"

    from pipeline.db.engine import get_session_factory
    SessionLocal = get_session_factory(engine)

    canonical_data = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v1.0.0",
        "analyzer_version": "0.15.0",
        "repository": test_url,
        "commit_sha": test_sha,
        "cache_snapshot_id": test_sha,
        "cache_key_basis": "git_sha",
        "analyzed_at_utc": "2026-09-19T22:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 2,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph": {"nodes": [], "edges": []},
        "health_score": {"composite_health_score": 90.0, "status": "complete"}
    }

    with SessionLocal() as session:
        run_id = persist_analysis(session, canonical_data)
        session.commit()

    # Submitting analysis request for exact same SHA returns cache_hit: True immediately
    res = client.post("/api/v1/analyses", json={"repo_url": test_url, "commit_sha": test_sha})
    assert res.status_code == 202
    job_resp = res.json()
    assert job_resp["cache_hit"] is True
    assert job_resp["status"] == "completed"
    assert job_resp["run_id"] == run_id


def test_commit_sha_propagation_and_resolution(temp_db_and_client, monkeypatch):
    """
    Regression tests for PART 6:
      - Resolved SHA is propagated into newly queued job
      - Worker task receives expected commit SHA
      - Explicit requested SHA remains respected
      - Unresolved SHA fallback policy leaves commit_sha as None
    """
    import pipeline.clone as clone_module
    import clone as clone_mod_flat
    import pipeline.api.routes as routes_module
    import api.routes as api_routes_module

    class CapturingQueue:
        def __init__(self):
            self.submissions = []

        def submit_job(self, job_id, db_url, cache_dir):
            self.submissions.append((job_id, db_url, cache_dir))

    queue = CapturingQueue()
    monkeypatch.setattr(routes_module, "get_worker_queue", lambda: queue)
    monkeypatch.setattr(api_routes_module, "get_worker_queue", lambda: queue)

    # Process one queued job through the real worker, but control the pipeline
    # result to isolate SHA propagation from Git/network/static-analyzer behavior.
    import pipeline.worker as worker_module
    pipeline_calls = []

    def controlled_pipeline(**kwargs):
        pipeline_calls.append(dict(kwargs))
        sha = kwargs.get("commit_sha")
        return {
            "repository": kwargs["repo_url"],
            "commit_sha": sha,
            "cache_snapshot_id": sha or "unknown-snapshot",
            "cache_key_basis": "git_sha" if sha else "content_hash",
            "schema_version": "test-schema",
            "cache_schema_version": "test-cache-schema",
            "analyzer_version": "test-analyzer",
            "analysis_status": "partial",
            "languages": ["python"],
            "files_analyzed": 1,
            "parse_errors": [],
            "static_analysis": {},
            "knowledge_graph_summary": {"nodes": 0, "edges": 0},
            "knowledge_graph": {"nodes": [], "edges": []},
            "health_score": {"status": "partial", "composite_health_score": None},
        }

    monkeypatch.setattr(worker_module, "run_pipeline", controlled_pipeline)

    client, engine, _ = temp_db_and_client
    test_url = "https://github.com/pytest-org/test-sha-repo"
    dummy_resolved_sha = "a1b2c3d4e5f678901234567890abcdef12345678"

    # Case 1: No commit_sha in request -> resolve_remote_sha returns dummy_resolved_sha
    monkeypatch.setattr(clone_module, "resolve_remote_sha", lambda url: dummy_resolved_sha)
    monkeypatch.setattr(clone_mod_flat, "resolve_remote_sha", lambda url: dummy_resolved_sha)

    res1 = client.post("/api/v1/analyses", json={"repo_url": test_url})
    assert res1.status_code == 202
    job1 = res1.json()
    assert job1["commit_sha"] == dummy_resolved_sha
    assert queue.submissions, "queued analysis should submit a worker task"
    submitted_job_id, submitted_db_url, submitted_cache_dir = queue.submissions[0]
    assert submitted_job_id == job1["job_id"]

    worker_module.process_job_task(submitted_job_id, submitted_db_url, submitted_cache_dir)
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0]["commit_sha"] == dummy_resolved_sha
    assert pipeline_calls[0]["repo_url"] == test_url

    # Case 2: Explicit requested SHA in request -> explicit SHA respected
    explicit_sha = "deadbeef12345678901234567890abcdef123456"
    res2 = client.post("/api/v1/analyses", json={"repo_url": test_url, "commit_sha": explicit_sha})
    assert res2.status_code == 202
    job2 = res2.json()
    assert job2["commit_sha"] == explicit_sha
    submitted_job_id, submitted_db_url, submitted_cache_dir = queue.submissions[1]
    assert submitted_job_id == job2["job_id"]
    worker_module.process_job_task(submitted_job_id, submitted_db_url, submitted_cache_dir)
    assert len(pipeline_calls) == 2
    assert pipeline_calls[1]["commit_sha"] == explicit_sha
    assert pipeline_calls[1]["repo_url"] == test_url

    # Case 3: Inability to resolve SHA -> commit_sha remains None (fallback policy)
    monkeypatch.setattr(clone_module, "resolve_remote_sha", lambda url: None)
    monkeypatch.setattr(clone_mod_flat, "resolve_remote_sha", lambda url: None)

    fallback_url = "https://github.com/pytest-org/fallback-sha-repo"
    res3 = client.post("/api/v1/analyses", json={"repo_url": fallback_url})
    assert res3.status_code == 202
    job3 = res3.json()
    assert job3["commit_sha"] is None



def test_nonexistent_ids_return_404(temp_db_and_client):
    client, _, _ = temp_db_and_client

    res_job = client.get("/api/v1/jobs/nonexistent-job-id")
    assert res_job.status_code == 404

    res_run = client.get("/api/v1/analyses/nonexistent-run-id")
    assert res_run.status_code == 404
