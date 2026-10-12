"""API force-refresh contract and worker bypass regression tests."""
from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline.db.models import AnalysisJob, AnalysisRun, SourceChunk, SourceEmbedding  # noqa: E402
from pipeline.worker import process_job_task  # noqa: E402
from pipeline.db.store import get_job_dict  # noqa: E402
from test_v0246_failure_states import REPO_URL, count, env, run_job  # noqa: E402,F401


def _submit(env, **extra):
    response = env["client"].post("/api/v1/analyses", json={"repo_url": REPO_URL, "commit_sha": env["repo"].commit_sha, **extra})
    assert response.status_code == 202, response.text
    return response.json()


def test_default_force_refresh_is_false_and_normal_cache_hit_unchanged(env):
    first = run_job(env)
    hit = _submit(env)
    assert hit["cache_hit"] is True
    assert hit["run_id"] == first["run_id"]


def test_force_refresh_persists_flag_skips_cache_and_creates_new_run(env, monkeypatch):
    first = run_job(env)
    import main as flat_main
    import pytest
    monkeypatch.setattr(flat_main, "load_cache", lambda *_args, **_kwargs: pytest.fail("force refresh read the file cache"))
    forced = _submit(env, force_refresh=True)
    assert forced["cache_hit"] is False
    with env["Session"]() as session:
        job = session.get(AnalysisJob, forced["job_id"])
        assert job.force_refresh is True
    process_job_task(forced["job_id"], env["db_url"], env["cache_dir"])
    with env["Session"]() as session:
        completed = get_job_dict(session, forced["job_id"])
    assert completed["run_id"] != first["run_id"]
    assert count(env, AnalysisRun) == 2


def test_force_refresh_active_job_returns_existing_job(env):
    active = _submit(env)
    again = _submit(env, force_refresh=True)
    assert again["job_id"] == active["job_id"]
    assert count(env, AnalysisJob) == 1


def test_force_refresh_wrong_type_is_422(env):
    response = env["client"].post("/api/v1/analyses", json={"repo_url": REPO_URL, "force_refresh": "yes"})
    assert response.status_code == 422


def test_force_refresh_does_not_duplicate_chunks_or_embeddings(env):
    first = run_job(env)
    forced = _submit(env, force_refresh=True)
    process_job_task(forced["job_id"], env["db_url"], env["cache_dir"])
    with env["Session"]() as session:
        completed = get_job_dict(session, forced["job_id"])
    second_run_id = completed["run_id"]
    assert count(env, AnalysisRun) == 2
    for model in (SourceChunk, SourceEmbedding):
        first_count = count(env, model, model.run_id == first["run_id"])
        second_count = count(env, model, model.run_id == second_run_id)
        assert first_count > 0 and second_count > 0
        assert first_count == second_count


def test_force_refresh_replaces_partial_with_new_complete_run(env, monkeypatch):
    import static_analysis
    from test_v0246_failure_states import _analysis
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis(security="unavailable"))
    partial = run_job(env)
    assert partial["status"] == "partial"
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis())
    forced = _submit(env, force_refresh=True)
    assert forced["cache_hit"] is False
    process_job_task(forced["job_id"], env["db_url"], env["cache_dir"])
    with env["Session"]() as session:
        refreshed = get_job_dict(session, forced["job_id"])
    assert refreshed["status"] == "completed"
    normal = _submit(env)
    assert normal["cache_hit"] is True
    assert normal["run_id"] == refreshed["run_id"]
    assert normal["run_id"] != partial["run_id"]
