"""
Sub-task 6.1: SQL Reads Oracle & Parity Test
"""
import os
import sys
import pytest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.engine import get_engine, create_all_tables
from db.store import (
    persist_analysis,
    get_analysis_findings_db,
    get_analysis_files_db,
    get_analysis_graph_db,
    get_analysis_summary_db,
    _run_to_dict,
)
from db.models import AnalysisRun, GraphNode
from sqlalchemy.orm import Session
from sqlalchemy import select, func


def _build_seeded_analysis():
    files_analyzed = 40
    nodes = []
    edges = []
    findings = []
    analyzers = ["bandit", "semgrep", "gitleaks"]
    severities = ["HIGH", "MEDIUM", "LOW", "ERROR"]

    for f_idx in range(files_analyzed):
        fp = f"src/file_{f_idx:02d}.py"
        nodes.append({"id": fp, "type": "file", "provenance": "filesystem-walk"})
        # Add function node
        fn_id = f"{fp}::func_{f_idx}"
        nodes.append({"id": fn_id, "type": "function", "name": f"func_{f_idx}", "file": fp, "start_line": 1, "end_line": 20, "provenance": "ast"})
        edges.append({"source": fp, "target": fn_id, "relation": "contains", "confidence": "structural_certain", "provenance": "ast"})

    # 150 findings across analyzers & severities
    for i in range(150):
        ana = analyzers[i % len(analyzers)]
        sev = severities[i % len(severities)]
        fp = f"src/file_{(i % files_analyzed):02d}.py"
        line = (i * 3) + 1 if i % 5 != 0 else None  # Some NULL lines
        f_dict = {
            "id": f"finding::{ana}::{i}",
            "type": "finding",
            "analyzer": ana,
            "severity": sev,
            "rule_id": f"rule_{i % 10}",
            "file": fp if i % 7 != 0 else None,  # Some NULL file paths
            "line": line,
            "message": f"Test finding message {i}",
            "provenance": ana,
        }
        findings.append(f_dict)

    static_analysis = {
        "bandit_findings": {"results": [f for f in findings if f["analyzer"] == "bandit"]},
        "semgrep_findings": {"results": [f for f in findings if f["analyzer"] == "semgrep"]},
        "gitleaks_findings": {"results": [f for f in findings if f["analyzer"] == "gitleaks"]},
    }

    return {
        "schema_version": "1.0.0",
        "cache_schema_version": "v5",
        "analyzer_version": "0.24.2",
        "repository": "https://github.com/oracle/test-repo",
        "commit_sha": "abc123def456",
        "cache_snapshot_id": "snap_oracle_123",
        "analyzed_at_utc": "2026-10-10T00:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": files_analyzed,
        "parse_errors": [],
        "static_analysis": static_analysis,
        "knowledge_graph_summary": {"total_nodes": len(nodes), "total_edges": len(edges)},
        "knowledge_graph": {"nodes": nodes, "edges": edges},
        "health_score": {"composite_health_score": 85.0, "status": "good"},
    }


def test_sql_findings_pagination_oracle_parity(tmp_path):
    """Exhaustive pagination oracle test over all combinations of filter, severity, limit, offset."""
    db_url = f"sqlite:///{tmp_path}/oracle_test.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    result_dict = _build_seeded_analysis()

    with Session(engine) as session:
        run_id = persist_analysis(session, result_dict)
        session.commit()

        # Build oracle from in-memory _run_to_dict
        run_obj = session.execute(select(AnalysisRun).where(AnalysisRun.id == run_id)).scalar_one()
        full_dict = _run_to_dict(session, run_obj)
        all_oracle_findings = []
        for n in full_dict["knowledge_graph"]["nodes"]:
            if n.get("type") == "finding":
                all_oracle_findings.append(n)

        analyzers_test = [None, "bandit", "semgrep", "gitleaks"]
        severities_test = [None, "HIGH", "MEDIUM", "LOW", "ERROR", "NOPE"]
        limits_test = [1, 7, 50, 1000]

        for ana in analyzers_test:
            for sev in severities_test:
                filtered_oracle = [
                    f for f in all_oracle_findings
                    if (ana is None or f.get("analyzer") == ana)
                    and (sev is None or f.get("severity") == sev)
                ]

                for limit in limits_test:
                    collected = []
                    offset = 0
                    while True:
                        page = get_analysis_findings_db(session, run_id, analyzer=ana, severity=sev, limit=limit, offset=offset)
                        assert page is not None
                        assert page["pagination"]["total"] == len(filtered_oracle)
                        items = page["findings"]
                        if not items:
                            break
                        assert len(items) <= limit
                        collected.extend(items)
                        offset += len(items)
                        if offset >= page["pagination"]["total"]:
                            break

                    assert len(collected) == len(filtered_oracle)


def test_unknown_run_returns_404_equivalent(tmp_path):
    """Unknown run_id returns None for all SQL read helpers."""
    db_url = f"sqlite:///{tmp_path}/unknown.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    with Session(engine) as session:
        assert get_analysis_findings_db(session, "nonexistent-id") is None
        assert get_analysis_files_db(session, "nonexistent-id") is None
        assert get_analysis_graph_db(session, "nonexistent-id") is None
        assert get_analysis_summary_db(session, "nonexistent-id") is None


def test_run_with_zero_findings_returns_total_zero(tmp_path):
    """Run with zero findings returns 200 shape with total = 0."""
    db_url = f"sqlite:///{tmp_path}/zero_findings.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    empty_analysis = _build_seeded_analysis()
    empty_analysis["static_analysis"] = {}

    with Session(engine) as session:
        run_id = persist_analysis(session, empty_analysis)
        session.commit()

        res = get_analysis_findings_db(session, run_id)
        assert res is not None
        assert res["pagination"]["total"] == 0
        assert res["findings"] == []


def test_graph_pages_with_large_node_list(tmp_path):
    """Graph pages with >1500 node IDs works without hitting SQLite 999 limit."""
    db_url = f"sqlite:///{tmp_path}/large_graph.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    nodes = [{"id": f"n_{i}", "type": "function", "name": f"f_{i}"} for i in range(1600)]
    edges = [{"source": f"n_{i}", "target": f"n_{i+1}", "relation": "calls"} for i in range(1599)]

    analysis = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v5",
        "analyzer_version": "0.24.2",
        "repository": "https://github.com/test/large-graph",
        "commit_sha": "1234567890",
        "cache_snapshot_id": "snap1",
        "analyzed_at_utc": "2026-10-10T00:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 1,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph_summary": {"total_nodes": 1600, "total_edges": 1599},
        "knowledge_graph": {"nodes": nodes, "edges": edges},
    }

    with Session(engine) as session:
        run_id = persist_analysis(session, analysis)
        session.commit()

        graph_res = get_analysis_graph_db(session, run_id, limit=1600, offset=0)
        assert graph_res is not None
        assert len(graph_res["nodes"]) == 1600
        assert len(graph_res["edges"]) == 1599


def test_legacy_run_summary_computation(tmp_path):
    """Legacy run with knowledge_graph_summary_json = NULL computes exact summary shape."""
    db_url = f"sqlite:///{tmp_path}/legacy_summary.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    analysis = _build_seeded_analysis()

    with Session(engine) as session:
        run_id = persist_analysis(session, analysis)
        session.commit()

        # Set knowledge_graph_summary_json to NULL to simulate legacy record
        session.execute(
            select(AnalysisRun).where(AnalysisRun.id == run_id)
        ).scalar_one().knowledge_graph_summary_json = None
        session.commit()

        summary = get_analysis_summary_db(session, run_id)
        assert summary is not None
        assert "knowledge_graph_summary" in summary
        assert summary["knowledge_graph_summary"]["total_nodes"] > 0


def test_get_queries_never_write_to_db(tmp_path):
    """GET read paths never mutate DB state."""
    db_url = f"sqlite:///{tmp_path}/read_only.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    analysis = _build_seeded_analysis()
    with Session(engine) as session:
        run_id = persist_analysis(session, analysis)
        session.commit()

        initial_node_count = session.execute(select(func.count(GraphNode.id))).scalar()

        # Perform GET operations
        get_analysis_summary_db(session, run_id)
        get_analysis_graph_db(session, run_id)
        get_analysis_findings_db(session, run_id)
        get_analysis_files_db(session, run_id)

        final_node_count = session.execute(select(func.count(GraphNode.id))).scalar()
        assert initial_node_count == final_node_count
