"""Configuration fingerprint regressions for DB and file cache compatibility."""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import update

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import util  # noqa: E402
import embeddings  # noqa: E402
import chunker  # noqa: E402
from pipeline.db.models import AnalysisRun, SourceChunk, SourceEmbedding  # noqa: E402
from test_v0246_failure_states import REPO_URL, count, env, run_job  # noqa: E402,F401


def test_analysis_config_fingerprint_is_deterministic_and_path_independent(tmp_path, monkeypatch):
    rules_a = tmp_path / "a.yml"
    rules_b = tmp_path / "b.yml"
    rules_a.write_text("rules: []\n")
    rules_b.write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules_a))
    first = util.analysis_config_fingerprint()
    assert first == util.analysis_config_fingerprint()
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules_b))
    assert util.analysis_config_fingerprint() == first


def test_fingerprint_changes_when_ruleset_contents_change(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yml"
    rules.write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules))
    first = util.analysis_config_fingerprint()
    rules.write_text("rules:\n  - id: changed\n")
    assert util.analysis_config_fingerprint() != first


def test_unset_semgrep_config_is_auto(monkeypatch):
    monkeypatch.delenv("SEMGREP_CONFIG", raising=False)
    assert util.semgrep_ruleset_identity() == "auto"


def test_fingerprint_changes_with_embedding_model_same_dimension(env, monkeypatch):
    monkeypatch.setattr(embeddings, "embedding_cache_identity", lambda: ("test-deterministic", "model-A", "1.0"))
    first = util.analysis_config_fingerprint()
    monkeypatch.setattr(embeddings, "embedding_cache_identity", lambda: ("test-deterministic", "model-B", "1.0"))
    assert util.analysis_config_fingerprint() != first


def test_fingerprint_changes_with_each_version_component(monkeypatch):
    baseline = util.analysis_config_fingerprint()
    with monkeypatch.context() as m:
        m.setattr(util, "CACHE_SCHEMA_VERSION", util.CACHE_SCHEMA_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(util, "ANALYZER_VERSION", util.ANALYZER_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(chunker, "SOURCE_CHUNKER_VERSION", "test-chunker-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(embeddings, "EMBEDDING_PIPELINE_VERSION", embeddings.EMBEDDING_PIPELINE_VERSION + "-next")
        assert util.analysis_config_fingerprint() != baseline
    with monkeypatch.context() as m:
        m.setattr(embeddings, "embedding_cache_identity", lambda: ("test-deterministic", "test-deterministic", "next-model-version"))
        assert util.analysis_config_fingerprint() != baseline


def test_unknown_embedding_provider_preserves_value_error(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "not-a-provider")
    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        util.analysis_config_fingerprint()
    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        util.build_cache_key("snapshot")


def _submit(env, **extra):
    payload = {"repo_url": REPO_URL, "commit_sha": env["repo"].commit_sha, **extra}
    response = env["client"].post("/api/v1/analyses", json=payload)
    assert response.status_code == 202, response.text
    return response.json()


def test_db_cache_invalidated_when_semgrep_rules_change(env, tmp_path, monkeypatch):
    rules = tmp_path / "rules.yml"
    rules.write_text("rules:\n  - id: test.first\n    pattern: print(...)\n    message: test\n    languages: [python]\n    severity: WARNING\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules))
    run_job(env)
    old_files = set(os.listdir(env["cache_dir"]))
    rules.write_text("rules:\n  - id: test.second\n    pattern: helper(...)\n    message: test\n    languages: [python]\n    severity: WARNING\n")
    second = _submit(env)
    assert second["cache_hit"] is False
    import main as flat_main
    original_load = flat_main.load_cache
    loaded_paths = []
    def tracking_load(path):
        loaded_paths.append(os.path.basename(path))
        return original_load(path)
    monkeypatch.setattr(flat_main, "load_cache", tracking_load)
    from pipeline.worker import process_job_task
    process_job_task(second["job_id"], env["db_url"], env["cache_dir"])
    assert not (old_files & set(loaded_paths)), "old file-cache entry was read after ruleset changed"
    with env["Session"]() as session:
        runs = session.query(AnalysisRun).all()
    assert len(runs) == 2
    assert runs[0].id != runs[1].id
    assert set(os.listdir(env["cache_dir"])) != old_files


def test_db_cache_invalidated_when_model_changes_same_dimension(env, monkeypatch):
    monkeypatch.setattr(embeddings, "embedding_cache_identity", lambda: ("test-deterministic", "model-A", "1.0"))
    run_job(env)
    monkeypatch.setattr(embeddings, "embedding_cache_identity", lambda: ("test-deterministic", "model-B", "1.0"))
    second = _submit(env)
    assert second["cache_hit"] is False
    from pipeline.worker import process_job_task
    process_job_task(second["job_id"], env["db_url"], env["cache_dir"])
    assert count(env, AnalysisRun) == 2


def test_db_cache_invalidated_when_chunker_version_changes(env, monkeypatch):
    run_job(env)
    monkeypatch.setattr(chunker, "SOURCE_CHUNKER_VERSION", "next-version")
    second = _submit(env)
    assert second["cache_hit"] is False


def test_legacy_null_fingerprint_is_not_reused(env):
    first = run_job(env)
    with env["Session"]() as session:
        session.execute(update(AnalysisRun).where(AnalysisRun.id == first["run_id"]).values(config_fingerprint=None))
        session.commit()
    second = _submit(env)
    assert second["cache_hit"] is False
    from pipeline.worker import process_job_task
    process_job_task(second["job_id"], env["db_url"], env["cache_dir"])
    with env["Session"]() as session:
        from pipeline.db.store import get_job_dict
        completed = get_job_dict(session, second["job_id"])
    assert completed["run_id"] != first["run_id"]
    assert count(env, AnalysisRun) == 2
    for model in (SourceChunk, SourceEmbedding):
        assert count(env, model, model.run_id == first["run_id"]) > 0
        assert count(env, model, model.run_id == completed["run_id"]) > 0
