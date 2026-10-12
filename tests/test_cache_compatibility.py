"""
v0.24.6 final refinement - cached results must be compatible with the CURRENT configuration.

Gaps closed (each test failed before):
  * the FILE cache key ignored the Semgrep ruleset (SEMGREP_CONFIG), so switching rules replayed
    findings produced under different rules for the same commit;
  * the DB cache hit (used by POST /analyses and by the worker) matched only repo + commit and ignored
    analyzer / cache-schema / embedding versions, so after an upgrade or a provider change the old run
    was served as if it were current, and the "re-run the analysis" advice of the 409 could never be
    satisfied because the re-run was answered from that same stale run.
Not covered by the DB check (documented limitation): the embedding MODEL name inside one provider is not
stored per row; the file-cache key and the retrieval dimension check cover that case.
"""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import update

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import util  # noqa: E402
from pipeline.db.models import AnalysisRun, SourceEmbedding  # noqa: E402
from test_v0246_failure_states import REPO_URL, count, env, run_job  # noqa: E402,F401  (env is a fixture)


# ------------------------------------------------------------------ file-cache key
def test_file_cache_key_depends_on_the_semgrep_ruleset(tmp_path, monkeypatch):
    rules = tmp_path / "rules.yml"
    rules.write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(rules))
    k1 = util.build_cache_key("snap")
    assert util.build_cache_key("snap") == k1, "key must be deterministic"

    rules.write_text("rules:\n  - id: other\n")
    k2 = util.build_cache_key("snap")
    assert k2 != k1, "editing the ruleset must change the key"

    copy = tmp_path / "copy.yml"
    copy.write_text(rules.read_text())
    monkeypatch.setenv("SEMGREP_CONFIG", str(copy))
    assert util.build_cache_key("snap") == k2, "identical rules at another path produce identical results"

    monkeypatch.setenv("SEMGREP_CONFIG", "auto")
    k_auto = util.build_cache_key("snap")
    assert k_auto != k2
    monkeypatch.delenv("SEMGREP_CONFIG")
    assert util.build_cache_key("snap") == k_auto, "unset means 'auto'"


def test_file_cache_key_for_a_rules_directory_tracks_every_file(tmp_path, monkeypatch):
    d = tmp_path / "rules"
    d.mkdir()
    (d / "a.yml").write_text("rules: []\n")
    monkeypatch.setenv("SEMGREP_CONFIG", str(d))
    k1 = util.build_cache_key("s")
    (d / "b.yml").write_text("rules: []\n")
    assert util.build_cache_key("s") != k1


# ------------------------------------------------------------------ DB cache hit
def _submit(env):
    r = env["client"].post("/api/v1/analyses", json={"repo_url": REPO_URL, "commit_sha": env["repo"].commit_sha})
    assert r.status_code == 202
    return r.json()


def test_same_version_run_is_still_a_cache_hit(env):
    first = run_job(env)
    hit = _submit(env)
    assert hit["cache_hit"] is True and hit["run_id"] == first["run_id"]


def test_run_from_an_older_analyzer_version_is_not_reused(env):
    first = run_job(env)
    with env["Session"]() as s:
        s.execute(update(AnalysisRun).where(AnalysisRun.id == first["run_id"]).values(analyzer_version="0.0.1-old"))
        s.commit()
    job = _submit(env)
    assert job["cache_hit"] is False, "a run produced by an older analyzer was served as current"
    assert job["status"] == "queued"

    second = run_job(env)
    assert second["run_id"] != first["run_id"]
    assert count(env, AnalysisRun) == 2


def test_run_from_an_older_cache_schema_is_not_reused(env):
    first = run_job(env)
    with env["Session"]() as s:
        s.execute(update(AnalysisRun).where(AnalysisRun.id == first["run_id"]).values(cache_schema_version="v0"))
        s.commit()
    assert _submit(env)["cache_hit"] is False


@pytest.mark.parametrize("column,value", [("model_name", "some-other-provider"), ("pipeline_version", "0-old")])
def test_run_with_incompatible_embeddings_is_not_reused(env, column, value):
    first = run_job(env)
    assert count(env, SourceEmbedding, SourceEmbedding.run_id == first["run_id"]) > 0
    with env["Session"]() as s:
        s.execute(update(SourceEmbedding).where(SourceEmbedding.run_id == first["run_id"]).values(**{column: value}))
        s.commit()
    job = _submit(env)
    assert job["cache_hit"] is False, f"embeddings with {column}={value!r} were treated as compatible"
