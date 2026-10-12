"""
v0.24.6 - failure-state integration tests.

These exercise the interaction between pipeline failures, health scoring,
the file cache, DB persistence and the HTTP API. They deliberately go through
the real worker (``process_job_task``) and the real FastAPI app; only the
external edges are replaced (git clone -> local fixture repo, analyzers ->
controlled output, embedding provider -> controlled failure).

Invariants guarded here:
  I1  A failed security scan is never reported as a clean scan.
  I2  A missing component is disclosed (status + reduced component set), never silent.
  I3  An unavailable embedding provider is never reported as a valid empty retrieval.
  I4  A failed job is never presented as completed; a partial run is never
      presented as a fully completed one (including on the cache-hit path).
  I5  A transient failure is not memoised: a retry can produce a better result,
      and a degraded result never overrides a better one.
  I6  Retries never duplicate or corrupt persisted rows.
  I7  Error messages stay useful without leaking secrets.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import clone as clone_flat
import main as flat_main
import static_analysis
import pipeline.api.routes as routes_module
import api.routes as api_routes_module
import pipeline.clone as clone_module
import pipeline.worker as worker_module
from pipeline.api.app import app
from pipeline.db.engine import create_all_tables, get_engine, get_session_factory
from pipeline.db.models import (
    AnalysisJobStage,
    AnalysisRun,
    GraphNode,
    SourceChunk,
    SourceEmbedding,
)
from pipeline.db.store import create_job, get_job_dict
from pipeline.worker import process_job_task

REPO_URL = "https://github.com/pytest-org/sample-repo"
SECRET = "sk-SUPERSECRET-should-never-appear-in-responses"


# --------------------------------------------------------------------------
# Controlled external edges
# --------------------------------------------------------------------------
def _analysis(security="success", semgrep="success", gitleaks="success", osv="success"):
    """Controlled analyzer output with explicit per-component statuses."""
    def block(status):
        b = {"status": status, "results": []}
        if status in ("failed", "unavailable"):
            b["error"] = f"controlled {status}"
        return b

    def factory(repo_root, parsed_files_rel=None, py_files_rel=None, **kwargs):
        files = sorted(parsed_files_rel or py_files_rel or [])
        return {
            "scope_policy": "production_code_only",
            "production_files_analyzed": len(files),
            "test_files_excluded": 0,
            "complexity": {"status": "success", "results": []},
            "maintainability": {"status": "success", "results": []},
            "security": block(security),
            "lizard_complexity": {"status": "unavailable", "results": []},
            "semgrep_findings": block(semgrep),
            "gitleaks_findings": block(gitleaks),
            "osv_vulnerabilities": block(osv),
        }

    return factory


def _failing_embeddings(source_chunks, repo_url, commit_sha=None, **kwargs):
    return [], {
        "status": "failed",
        "error": "Embedding provider unavailable (controlled)",
        "total_embeddings": 0,
        "provider_name": "controlled",
    }


@pytest.fixture
def env(tmp_path, sample_git_repo, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'fs.db'}"
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DIR", cache_dir)

    engine = get_engine(db_url)
    create_all_tables(engine)

    orig_clone = clone_module.clone_repository

    def local_clone(url, dest, commit_sha=None):
        return orig_clone(sample_git_repo.path, dest, commit_sha=commit_sha or sample_git_repo.commit_sha)

    for mod in (clone_module, clone_flat):
        monkeypatch.setattr(mod, "clone_repository", local_clone)
        monkeypatch.setattr(mod, "resolve_remote_sha", lambda url: sample_git_repo.commit_sha)

    class NoOpQueue:
        def submit_job(self, job_id, db_url, cache_dir):
            pass

    for mod in (routes_module, api_routes_module):
        monkeypatch.setattr(mod, "get_worker_queue", lambda: NoOpQueue())

    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis())

    with TestClient(app) as client:
        yield {
            "client": client,
            "engine": engine,
            "db_url": db_url,
            "cache_dir": cache_dir,
            "Session": get_session_factory(engine),
            "repo": sample_git_repo,
        }
    engine.dispose()


def run_job(env) -> dict:
    Session = env["Session"]
    with Session() as s:
        job = create_job(s, REPO_URL, commit_sha=env["repo"].commit_sha)
        job_id = job.id
        s.commit()
    process_job_task(job_id, env["db_url"], env["cache_dir"])
    with Session() as s:
        return get_job_dict(s, job_id)


def count(env, model, *where) -> int:
    with env["Session"]() as s:
        stmt = select(func.count()).select_from(model)
        for w in where:
            stmt = stmt.where(w)
        return s.execute(stmt).scalar()


def cache_files(env) -> list[str]:
    return [f for f in os.listdir(env["cache_dir"]) if f.endswith(".json")]


# --------------------------------------------------------------------------
# I1 / I2 - security scan failure and health score honesty
# --------------------------------------------------------------------------
def test_failed_security_scan_is_never_reported_clean(env, monkeypatch):
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis(security="failed", semgrep="failed"))
    job = run_job(env)
    assert job["status"] == "partial", job
    body = env["client"].get(f"/api/v1/analyses/{job['run_id']}").json()

    sa = body["static_analysis"]
    assert sa["security"]["status"] == "failed"
    assert sa["semgrep_findings"]["status"] == "failed"
    # A failed scan has no results, but must never be labelled success/complete.
    assert body["analysis_status"] != "complete"
    hs = body["health_score"]
    assert hs["reduced_component_set"] is True
    assert "security" not in hs["components_scored"] and "sast" not in hs["components_scored"]
    assert "reduced component set" in hs["note"]


def test_failed_component_never_silently_improves_the_score(env):
    """A failed scan removes its component from the score; that must be disclosed, not hidden."""
    from pipeline.health_score import compute_health_score

    clean = compute_health_score(_analysis()("x", ["a.py"]))
    failed = compute_health_score(_analysis(security="failed", semgrep="failed")("x", ["a.py"]))

    assert set(failed["components_scored"]) < set(clean["components_scored"])
    assert failed["reduced_component_set"] is True
    assert failed["status"] != "complete"
    assert "reduced component set" in failed["note"]
    # The missing components are named so a reader can see what was NOT measured.
    assert "security" in failed["note"] and "sast" in failed["note"]


# --------------------------------------------------------------------------
# I3 - embedding provider unavailable
# --------------------------------------------------------------------------
def test_embedding_failure_is_reported_as_failed_stage(env, monkeypatch):
    monkeypatch.setattr(flat_main, "generate_source_embeddings", _failing_embeddings)
    job = run_job(env)
    # Embedding failure is non-fatal for the job (existing, tested design)...
    assert job["status"] in ("completed", "partial")
    with env["Session"]() as s:
        stage = s.execute(
            select(AnalysisJobStage).where(
                AnalysisJobStage.job_id == job["job_id"], AnalysisJobStage.stage_name == "embedding"
            )
        ).scalar_one()
    # ...but the stage must not claim success.
    assert stage.status == "failed", f"embedding stage reported {stage.status!r}: {stage.detail!r}"


def test_unavailable_embeddings_are_not_an_empty_retrieval_result(env, monkeypatch):
    monkeypatch.setattr(flat_main, "generate_source_embeddings", _failing_embeddings)
    job = run_job(env)
    run_id = job["run_id"]
    assert count(env, SourceChunk, SourceChunk.run_id == run_id) > 0
    assert count(env, SourceEmbedding, SourceEmbedding.run_id == run_id) == 0

    r = env["client"].post(f"/api/v1/analyses/{run_id}/retrieve", json={"query": "helper", "top_k": 3})
    assert r.status_code == 409, f"got {r.status_code}: {r.text[:200]}"
    assert "embedding" in r.json()["detail"].lower()

    a = env["client"].post(f"/api/v1/analyses/{run_id}/ask", json={"question": "What does helper do?", "top_k": 3})
    assert a.status_code == 409, f"got {a.status_code}: {a.text[:200]}"


def test_repository_with_no_chunks_is_a_legitimate_empty_retrieval(env, monkeypatch):
    """Counter-test: the new guard must not turn a genuinely empty repo into an error."""
    monkeypatch.setattr(flat_main, "generate_repository_chunks", lambda *a, **k: [])
    job = run_job(env)
    r = env["client"].post(f"/api/v1/analyses/{job['run_id']}/retrieve", json={"query": "x", "top_k": 3})
    assert r.status_code == 200
    assert r.json()["total_retrieved"] == 0


# --------------------------------------------------------------------------
# I7 - LLM provider failure
# --------------------------------------------------------------------------
def test_llm_init_failure_is_503_and_leaks_nothing(env, monkeypatch):
    job = run_job(env)
    import rag.llm as flat_llm

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setitem(sys.modules, "openai", None)  # import openai -> ImportError (hermetic)
    flat_llm.reset_llm_provider_cache()
    try:
        r = env["client"].post(
            f"/api/v1/analyses/{job['run_id']}/ask", json={"question": "What does helper do?", "top_k": 3}
        )
    finally:
        flat_llm.reset_llm_provider_cache()
    assert r.status_code == 503, r.text[:200]
    assert SECRET not in r.text
    assert "Traceback" not in r.text
    assert "answer" not in r.json()  # no fabricated answer


# --------------------------------------------------------------------------
# I4 / I6 - database failure during a job
# --------------------------------------------------------------------------
def test_db_failure_during_persist_fails_job_and_leaves_no_partial_rows(env, monkeypatch):
    real_persist = worker_module.persist_analysis

    def persist_then_die(session, result):
        real_persist(session, result)  # rows are added to the session...
        raise RuntimeError(f"disk I/O error while writing (token={SECRET})")

    monkeypatch.setattr(worker_module, "persist_analysis", persist_then_die)
    job = run_job(env)
    assert job["status"] == "failed"
    assert job["run_id"] is None
    assert "Finalization error" in job["error_message"]
    # ...but nothing may be committed.
    assert count(env, AnalysisRun) == 0
    assert count(env, GraphNode) == 0
    assert count(env, SourceChunk) == 0


# --------------------------------------------------------------------------
# I4 / I6 - retry after a failed stage
# --------------------------------------------------------------------------
def test_retry_after_clone_failure_recovers_without_duplicates(env, monkeypatch):
    good_clone = clone_flat.clone_repository

    def broken(url, dest, commit_sha=None):
        raise RuntimeError("Controlled clone failure")

    for mod in (clone_module, clone_flat):
        monkeypatch.setattr(mod, "clone_repository", broken)
    first = run_job(env)
    assert first["status"] == "failed" and first["run_id"] is None
    assert count(env, AnalysisRun) == 0

    for mod in (clone_module, clone_flat):
        monkeypatch.setattr(mod, "clone_repository", good_clone)
    second = run_job(env)
    assert second["status"] in ("completed", "partial") and second["run_id"]
    assert count(env, AnalysisRun) == 1
    with env["Session"]() as s:
        ids = s.execute(select(SourceChunk.id).where(SourceChunk.run_id == second["run_id"])).scalars().all()
    assert len(ids) == len(set(ids)) > 0


def test_embedding_failure_is_not_memoised_so_a_retry_can_recover(env, monkeypatch):
    real_embed = flat_main.generate_source_embeddings
    monkeypatch.setattr(flat_main, "generate_source_embeddings", _failing_embeddings)
    first = run_job(env)
    assert count(env, SourceEmbedding, SourceEmbedding.run_id == first["run_id"]) == 0
    assert cache_files(env) == [], "a result with failed embeddings must not be written to the file cache"

    # The provider recovers. A retry must not be served the embedding-less run.
    monkeypatch.setattr(flat_main, "generate_source_embeddings", real_embed)
    second = run_job(env)
    assert second["run_id"] != first["run_id"], "retry was served the run that has no embeddings"
    assert count(env, SourceEmbedding, SourceEmbedding.run_id == second["run_id"]) > 0
    r = env["client"].post(f"/api/v1/analyses/{second['run_id']}/retrieve", json={"query": "helper", "top_k": 3})
    assert r.status_code == 200 and r.json()["total_retrieved"] > 0


# --------------------------------------------------------------------------
# I4 / I5 - degraded runs and the cache-hit path
# --------------------------------------------------------------------------
def test_cache_hit_of_partial_run_is_reported_partial_not_completed(env, monkeypatch):
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis(security="failed"))
    first = run_job(env)
    assert first["status"] == "partial"

    r = env["client"].post("/api/v1/analyses", json={"repo_url": REPO_URL, "commit_sha": env["repo"].commit_sha})
    assert r.status_code == 202
    hit = r.json()
    assert hit["cache_hit"] is True
    assert hit["run_id"] == first["run_id"]
    assert hit["status"] == "partial", f"a partial run was presented as {hit['status']!r}"


def test_degraded_retry_does_not_replace_a_better_run_and_better_replaces_degraded(env, monkeypatch):
    # 1) a degraded (failed-security) run exists
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis(security="failed"))
    degraded = run_job(env)
    assert degraded["status"] == "partial"
    # no memoisation of a result that contains a failed component
    assert cache_files(env) == []

    # 2) the tool recovers; a retry must produce a NEW, better run (not reuse the degraded one)
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis())
    better = run_job(env)
    assert better["run_id"] != degraded["run_id"], "retry was served the degraded run"
    assert count(env, AnalysisRun) == 2

    # 3) a later degraded retry must not displace the better run
    monkeypatch.setattr(static_analysis, "analyze_repository", _analysis(security="failed"))
    for f in cache_files(env):
        os.remove(os.path.join(env["cache_dir"], f))
    again = run_job(env)
    assert again["run_id"] == better["run_id"]
    assert count(env, AnalysisRun) == 2


def test_failed_job_is_not_presented_as_completed(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(static_analysis, "analyze_repository", boom)
    job = run_job(env)
    assert job["status"] == "failed"
    assert job["run_id"] is None
    assert job["error_message"]
    assert count(env, AnalysisRun) == 0
    assert cache_files(env) == []


# --------------------------------------------------------------------------
# I4 - stale-job recovery with the default (env-driven) threshold
# --------------------------------------------------------------------------
def test_stale_job_cleanup_default_threshold_reads_env(env, monkeypatch):
    """cleanup_stale_jobs() without an explicit threshold read os.environ but store.py never imported
    os, so the default path raised NameError (latent since 0.24.2)."""
    from pipeline.db.store import cleanup_stale_jobs

    monkeypatch.setenv("JOB_STALE_SECONDS", "not-a-number")  # invalid -> falls back to 1800, must not crash
    assert cleanup_stale_jobs(env["engine"]) == 0
    monkeypatch.setenv("JOB_STALE_SECONDS", "60")
    assert cleanup_stale_jobs(env["engine"]) == 0
