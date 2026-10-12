"""
S14: Persistent database storage tests.

All tests use SQLite in-memory so no external DB service is required.
Tests run in CI and locally without any PostgreSQL setup.

Coverage:
  1.  Repository creation
  2.  Repository deduplication (upsert)
  3.  Repeated repository analysis (new run each time)
  4.  Snapshot uniqueness (same snapshot_id -> same Snapshot row)
  5.  Analysis-run lifecycle (pending -> complete)
  6.  Partial-run storage
  7.  Failed-run storage
  8.  Graph-node persistence
  9.  Graph-edge persistence
  10. Finding persistence
  11. Health-score persistence
  12. Analyzer-version tracking
  13. Duplicate-prevention (snapshot uq constraint)
  14. Transaction rollback / error behavior
  15. Canonical round-trip: persist then retrieve, verify key fields
  16. get_latest_analysis returns newest complete run
  17. get_all_runs_for_repo returns all runs
  18. Multiple repos are independent
"""
from __future__ import annotations
import json
import sys
import os
import pytest
from datetime import datetime, timezone

# Make pipeline.db importable from the tests directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from db.engine import get_engine, create_all_tables, drop_all_tables, get_session_factory
from db.models import Repository, Snapshot, AnalysisRun, AnalyzerResult, FileRecord, EntityRecord, GraphNode, GraphEdge, Finding, HealthScore
from db.store import persist_analysis, get_latest_analysis, get_analysis_by_run_id, get_all_runs_for_repo
from sqlalchemy.orm import Session
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def engine():
    """Fresh in-memory SQLite engine per test."""
    eng = get_engine("sqlite:///:memory:")
    create_all_tables(eng)
    yield eng
    drop_all_tables(eng)
    eng.dispose()


@pytest.fixture(scope="function")
def session(engine):
    """A session bound to the in-memory engine."""
    factory = get_session_factory(engine)
    with factory() as sess:
        yield sess


# ---------------------------------------------------------------------------
# Minimal canonical result fixtures
# ---------------------------------------------------------------------------

def _make_result(
    repo_url: str = "https://github.com/test/repo",
    snapshot_id: str = "abc123sha",
    commit_sha: str = "abc123sha",
    status: str = "complete",
    analyzer_version: str = "0.13.0",
    health_score: float = 87.5,
    include_graph: bool = True,
    include_findings: bool = False,
) -> dict:
    """Build a minimal but structurally valid canonical analysis result dict."""
    nodes = []
    edges = []
    if include_graph:
        nodes = [
            {"id": "app.py", "type": "file", "provenance": "filesystem-walk"},
            {"id": "app.py::MyClass:1", "type": "class", "name": "MyClass",
             "file": "app.py", "start_line": 1, "end_line": 20,
             "bases": [], "provenance": "tree-sitter-python:AST-walk"},
            {"id": "app.py::my_func:5", "type": "function", "name": "my_func",
             "file": "app.py", "start_line": 5, "end_line": 10,
             "class_owner": "MyClass", "provenance": "tree-sitter-python:AST-walk"},
        ]
        edges = [
            {"source": "app.py", "target": "app.py::MyClass:1",
             "relation": "contains", "confidence": "structural_certain",
             "provenance": "tree-sitter-python:AST-walk"},
            {"source": "app.py::MyClass:1", "target": "app.py::my_func:5",
             "relation": "contains", "confidence": "structural_certain",
             "provenance": "tree-sitter-python:AST-walk"},
        ]
    if include_findings:
        nodes.append({
            "id": "finding::bandit::B601::app.py:7::0",
            "type": "finding",
            "analyzer": "bandit",
            "rule_id": "B601",
            "severity": "HIGH",
            "message": "Possible shell injection",
            "file": "app.py",
            "line": 7,
            "provenance": "bandit",
        })

    return {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": analyzer_version,
        "repository": repo_url,
        "commit_sha": commit_sha,
        "cache_snapshot_id": snapshot_id,
        "cache_key_basis": "git_sha (fresh clone, trusted)",
        "analyzed_at_utc": "2026-09-19T10:00:00+00:00",
        "languages": ["python"],
        "analysis_status": status,
        "files_analyzed": 1,
        "parse_errors": [],
        "static_analysis": {
            "scope_policy": "production_code_only",
            "production_files_analyzed": 1,
            "test_files_excluded": 0,
            "complexity": {
                "status": "success",
                "results": [{"file": "app.py", "function": "my_func", "line": 5,
                             "cyclomatic_complexity": 3, "rank": "A",
                             "provenance": "radon:6.0.1:cc_visit"}],
                "provenance": "radon:6.0.1:cc_visit",
            },
            "maintainability": {
                "status": "success",
                "results": [{"file": "app.py", "maintainability_index": 75.0,
                             "provenance": "radon:6.0.1:mi_visit"}],
                "provenance": "radon:6.0.1:mi_visit",
            },
            "security": {
                "status": "success",
                "results": [],
                "provenance": "bandit:1.7.0",
            },
        },
        "knowledge_graph_summary": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
        "knowledge_graph": {"nodes": nodes, "edges": edges},
        "health_score": {
            "composite_health_score": health_score,
            "status": status,
            "sub_scores": {"complexity": 90.0, "maintainability": 85.0, "security": 100.0},
            "component_statuses": {"complexity": "success", "maintainability": "success", "security": "success"},
            "weights_used": {"complexity": 0.35, "maintainability": 0.35, "security": 0.30},
            "weights_renormalized": False,
            "missing_components": [],
            "formula": "weighted average",
            "scope_policy": "production_code_only",
        },
    }


# ---------------------------------------------------------------------------
# 1. Repository creation
# ---------------------------------------------------------------------------

def test_repository_creation(session):
    result = _make_result()
    run_id = persist_analysis(session, result)
    session.commit()

    repo = session.execute(
        select(Repository).where(Repository.repo_url == "https://github.com/test/repo")
    ).scalar_one()
    assert repo is not None
    assert repo.repo_url == "https://github.com/test/repo"


# ---------------------------------------------------------------------------
# 2. Repository deduplication (upsert)
# ---------------------------------------------------------------------------

def test_repository_deduplication(session):
    """Two analyses for the same repo_url should share the same Repository row."""
    result1 = _make_result(snapshot_id="sha001")
    result2 = _make_result(snapshot_id="sha002")
    persist_analysis(session, result1)
    persist_analysis(session, result2)
    session.commit()

    repos = session.execute(select(Repository)).scalars().all()
    assert len(repos) == 1, "Only one Repository row should exist"


# ---------------------------------------------------------------------------
# 3. Repeated repository analysis (multiple runs)
# ---------------------------------------------------------------------------

def test_repeated_analysis_creates_new_runs(session):
    """Two analyses on same snapshot create two distinct AnalysisRun rows."""
    result = _make_result()
    run_id1 = persist_analysis(session, result)
    run_id2 = persist_analysis(session, result)
    session.commit()

    assert run_id1 != run_id2
    runs = session.execute(select(AnalysisRun)).scalars().all()
    assert len(runs) == 2


# ---------------------------------------------------------------------------
# 4. Snapshot uniqueness
# ---------------------------------------------------------------------------

def test_snapshot_uniqueness(session):
    """Same snapshot_id -> same Snapshot row (never duplicated)."""
    result = _make_result(snapshot_id="fixed-sha")
    persist_analysis(session, result)
    persist_analysis(session, result)
    session.commit()

    snaps = session.execute(select(Snapshot)).scalars().all()
    assert len(snaps) == 1, "Snapshot should be deduplicated by (repo_id, snapshot_id)"


# ---------------------------------------------------------------------------
# 5. Analysis-run lifecycle (status stored correctly)
# ---------------------------------------------------------------------------

def test_analysis_run_status_complete(session):
    result = _make_result(status="complete")
    run_id = persist_analysis(session, result)
    session.commit()

    run = session.get(AnalysisRun, run_id)
    assert run.status == "complete"
    assert run.analysis_status == "complete"


# ---------------------------------------------------------------------------
# 6. Partial-run storage
# ---------------------------------------------------------------------------

def test_partial_run_storage(session):
    result = _make_result(status="partial")
    run_id = persist_analysis(session, result)
    session.commit()

    run = session.get(AnalysisRun, run_id)
    assert run.status == "partial"
    assert run.analysis_status == "partial"


# ---------------------------------------------------------------------------
# 7. Failed-run storage
# ---------------------------------------------------------------------------

def test_failed_run_storage(session):
    result = _make_result(status="failed")
    run_id = persist_analysis(session, result)
    session.commit()

    run = session.get(AnalysisRun, run_id)
    assert run.status == "failed"


# ---------------------------------------------------------------------------
# 8. Graph-node persistence
# ---------------------------------------------------------------------------

def test_graph_node_persistence(session):
    result = _make_result(include_graph=True)
    run_id = persist_analysis(session, result)
    session.commit()

    nodes = session.execute(
        select(GraphNode).where(GraphNode.run_id == run_id)
    ).scalars().all()
    node_types = {n.node_type for n in nodes}
    assert "file" in node_types
    assert "class" in node_types
    assert "function" in node_types
    # We have 3 nodes in _make_result
    assert len(nodes) == 3


# ---------------------------------------------------------------------------
# 9. Graph-edge persistence
# ---------------------------------------------------------------------------

def test_graph_edge_persistence(session):
    result = _make_result(include_graph=True)
    run_id = persist_analysis(session, result)
    session.commit()

    edges = session.execute(
        select(GraphEdge).where(GraphEdge.run_id == run_id)
    ).scalars().all()
    assert len(edges) == 2
    relations = {e.relation for e in edges}
    assert "contains" in relations
    for e in edges:
        assert e.confidence == "structural_certain"


# ---------------------------------------------------------------------------
# 10. Finding persistence
# ---------------------------------------------------------------------------

def test_finding_persistence(session):
    result = _make_result(include_findings=True)
    run_id = persist_analysis(session, result)
    session.commit()

    findings = session.execute(
        select(Finding).where(Finding.run_id == run_id)
    ).scalars().all()
    assert len(findings) == 1
    f = findings[0]
    assert f.analyzer == "bandit"
    assert f.rule_id == "B601"
    assert f.severity == "HIGH"
    assert f.file_path == "app.py"
    assert f.line == 7


# ---------------------------------------------------------------------------
# 11. Health-score persistence
# ---------------------------------------------------------------------------

def test_health_score_persistence(session):
    result = _make_result(health_score=87.5)
    run_id = persist_analysis(session, result)
    session.commit()

    run = session.get(AnalysisRun, run_id)
    hs = run.health_score
    assert hs is not None
    assert abs(hs.composite_health_score - 87.5) < 0.01
    assert hs.status == "complete"
    sub = json.loads(hs.sub_scores_json)
    assert sub["complexity"] == 90.0
    assert sub["maintainability"] == 85.0
    assert hs.weights_renormalized is False


# ---------------------------------------------------------------------------
# 12. Analyzer-version tracking
# ---------------------------------------------------------------------------

def test_analyzer_version_tracking(session):
    result_v13 = _make_result(analyzer_version="0.13.0", snapshot_id="sha-v13")
    result_v14 = _make_result(analyzer_version="0.14.0", snapshot_id="sha-v14")
    id1 = persist_analysis(session, result_v13)
    id2 = persist_analysis(session, result_v14)
    session.commit()

    run1 = session.get(AnalysisRun, id1)
    run2 = session.get(AnalysisRun, id2)
    assert run1.analyzer_version == "0.13.0"
    assert run2.analyzer_version == "0.14.0"
    assert run1.schema_version == "1.0.0"
    assert run1.cache_schema_version == "v4"


# ---------------------------------------------------------------------------
# 13. Duplicate prevention (UniqueConstraint on snapshot)
# ---------------------------------------------------------------------------

def test_snapshot_uq_constraint_is_enforced(session):
    """Persisting two runs with same snapshot_id must reuse the same snapshot row."""
    result = _make_result(snapshot_id="deterministic-sha")
    persist_analysis(session, result)
    persist_analysis(session, result)
    session.commit()

    snaps = session.execute(select(Snapshot)).scalars().all()
    runs = session.execute(select(AnalysisRun)).scalars().all()
    assert len(snaps) == 1
    assert len(runs) == 2  # Two runs, but same snapshot


# ---------------------------------------------------------------------------
# 14. Transaction rollback / error behavior
# ---------------------------------------------------------------------------

def test_transaction_rollback_leaves_no_partial_data(session):
    """A rollback after persist_analysis must leave the DB empty."""
    result = _make_result()
    persist_analysis(session, result)
    # Deliberately rollback instead of commit
    session.rollback()

    repos = session.execute(select(Repository)).scalars().all()
    runs = session.execute(select(AnalysisRun)).scalars().all()
    assert len(repos) == 0, "Rollback must remove the repository row"
    assert len(runs) == 0, "Rollback must remove the run row"


# ---------------------------------------------------------------------------
# 15. Canonical round-trip
# ---------------------------------------------------------------------------

def test_canonical_round_trip(session):
    """Persist then retrieve -- key canonical fields must match."""
    result = _make_result(
        repo_url="https://github.com/canonical/roundtrip",
        snapshot_id="roundtrip-sha-999",
        health_score=77.3,
    )
    run_id = persist_analysis(session, result)
    session.commit()

    retrieved = get_analysis_by_run_id(session, run_id)
    assert retrieved is not None
    assert retrieved["repository"] == result["repository"]
    assert retrieved["cache_snapshot_id"] == result["cache_snapshot_id"]
    assert retrieved["analyzer_version"] == result["analyzer_version"]
    assert retrieved["schema_version"] == result["schema_version"]
    assert retrieved["files_analyzed"] == result["files_analyzed"]
    assert retrieved["languages"] == result["languages"]
    assert retrieved["analysis_status"] == result["analysis_status"]

    # Health score round-trip
    hs_in = result["health_score"]
    hs_out = retrieved["health_score"]
    assert abs(hs_out["composite_health_score"] - hs_in["composite_health_score"]) < 0.01
    assert hs_out["status"] == hs_in["status"]
    assert hs_out["sub_scores"] == hs_in["sub_scores"]

    # Graph nodes present
    node_ids = {n["id"] for n in retrieved["knowledge_graph"]["nodes"]}
    assert "app.py" in node_ids
    assert "app.py::MyClass:1" in node_ids

    # Edges present
    assert len(retrieved["knowledge_graph"]["edges"]) == 2


# ---------------------------------------------------------------------------
# 16. get_latest_analysis returns the newest complete run
# ---------------------------------------------------------------------------

def test_get_latest_analysis_returns_newest(session):
    repo_url = "https://github.com/test/latest-check"
    r1 = _make_result(repo_url=repo_url, snapshot_id="sha-old", health_score=60.0)
    r2 = _make_result(repo_url=repo_url, snapshot_id="sha-new", health_score=90.0)
    persist_analysis(session, r1)
    persist_analysis(session, r2)
    session.commit()

    latest = get_latest_analysis(session, repo_url)
    assert latest is not None
    # Both are "complete" -- should return the second (newer) one
    assert abs(latest["health_score"]["composite_health_score"] - 90.0) < 0.01


# ---------------------------------------------------------------------------
# 17. get_all_runs_for_repo returns all runs
# ---------------------------------------------------------------------------

def test_get_all_runs_for_repo(session):
    repo_url = "https://github.com/test/all-runs"
    for i in range(3):
        r = _make_result(repo_url=repo_url, snapshot_id=f"sha-{i}")
        persist_analysis(session, r)
    session.commit()

    runs = get_all_runs_for_repo(session, repo_url)
    assert len(runs) == 3


# ---------------------------------------------------------------------------
# 18. Multiple repos are independent
# ---------------------------------------------------------------------------

def test_multiple_repos_are_independent(session):
    r1 = _make_result(repo_url="https://github.com/org/repo-alpha", snapshot_id="sha-alpha")
    r2 = _make_result(repo_url="https://github.com/org/repo-beta", snapshot_id="sha-beta")
    persist_analysis(session, r1)
    persist_analysis(session, r2)
    session.commit()

    repos = session.execute(select(Repository)).scalars().all()
    assert len(repos) == 2

    alpha_runs = get_all_runs_for_repo(session, "https://github.com/org/repo-alpha")
    beta_runs = get_all_runs_for_repo(session, "https://github.com/org/repo-beta")
    assert len(alpha_runs) == 1
    assert len(beta_runs) == 1
    assert alpha_runs[0]["repository"] == "https://github.com/org/repo-alpha"
    assert beta_runs[0]["repository"] == "https://github.com/org/repo-beta"


# ---------------------------------------------------------------------------
# 19. Analyzer results are stored per tool
# ---------------------------------------------------------------------------

def test_analyzer_results_stored_per_tool(session):
    result = _make_result()
    run_id = persist_analysis(session, result)
    session.commit()

    ars = session.execute(
        select(AnalyzerResult).where(AnalyzerResult.run_id == run_id)
    ).scalars().all()
    names = {ar.analyzer_name for ar in ars}
    assert "complexity" in names
    assert "maintainability" in names
    assert "security" in names


# ---------------------------------------------------------------------------
# 20. File records are created for file nodes
# ---------------------------------------------------------------------------

def test_file_records_created(session):
    result = _make_result(include_graph=True)
    run_id = persist_analysis(session, result)
    session.commit()

    frs = session.execute(
        select(FileRecord).where(FileRecord.run_id == run_id)
    ).scalars().all()
    assert len(frs) >= 1
    paths = {fr.file_path for fr in frs}
    assert "app.py" in paths


# ---------------------------------------------------------------------------
# 21. DB engine creates tables idempotently
# ---------------------------------------------------------------------------

def test_create_all_tables_is_idempotent(engine):
    """create_all_tables can be called multiple times without error."""
    from db.engine import create_all_tables
    create_all_tables(engine)  # second call
    create_all_tables(engine)  # third call
    # If we reach here without exception, the test passes


# ---------------------------------------------------------------------------
# 22. get_latest_analysis returns None for unknown repo
# ---------------------------------------------------------------------------

def test_get_latest_analysis_unknown_repo(session):
    result = get_latest_analysis(session, "https://github.com/doesnt/exist")
    assert result is None


# ---------------------------------------------------------------------------
# 23. get_analysis_by_run_id returns None for unknown run
# ---------------------------------------------------------------------------

def test_get_analysis_by_run_id_unknown(session):
    result = get_analysis_by_run_id(session, "00000000-0000-0000-0000-000000000000")
    assert result is None


# ---------------------------------------------------------------------------
# 24. Alembic migration upgrade/downgrade runs without error
# ---------------------------------------------------------------------------

def test_alembic_migration_upgrade_downgrade(tmp_path):
    """
    Verify the Alembic initial migration can be applied and reversed
    against a fresh SQLite database.
    """
    db_path = str(tmp_path / "test_migration.db")
    db_url = f"sqlite:///{db_path}"

    import subprocess, sys
    result_up = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": db_url},
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result_up.returncode == 0, f"alembic upgrade failed:\n{result_up.stderr}"

    result_down = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", "base"],
        capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": db_url},
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result_down.returncode == 0, f"alembic downgrade failed:\n{result_down.stderr}"
