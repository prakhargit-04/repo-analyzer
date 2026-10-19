"""
Session 25 Production Trust regression tests.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from health_score import compute_health_score, HEALTH_FORMULA_VERSION
from db.store import _add_reduced_set_fields


def test_health_score_includes_score_validation_and_analyzer_coverage():
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "A"}]},
        "maintainability": {"status": "success", "results": [{"maintainability_index": 85.0}]},
        "security": {"status": "success", "results": []},
        "semgrep_findings": {"status": "success", "results": []},
        "gitleaks_findings": {"status": "success", "results": []},
        "osv_vulnerabilities": {"status": "unavailable", "results": []},
    }
    result = compute_health_score(analysis)

    # B1: Score honesty
    assert "score_validation" in result, "health_score must contain score_validation dict"
    val = result["score_validation"]
    assert val["validated"] is False
    assert val["basis"] == "heuristic weights not empirically validated"
    assert val["formula_version"] == HEALTH_FORMULA_VERSION

    assert "analyzer_coverage" in result, "health_score must contain analyzer_coverage dict"
    cov = result["analyzer_coverage"]
    assert "component_statuses" in cov
    assert "components_analyzed" in cov
    assert "components_not_analyzed" in cov
    assert "vulnerabilities" in cov["components_not_analyzed"]
    assert "complexity" in cov["components_analyzed"]


def test_old_cached_results_without_validation_fields_backfilled():
    # Simulate an older stored health_score without score_validation or analyzer_coverage
    old_hs = {
        "composite_health_score": 85.0,
        "sub_scores": {"complexity": 80.0, "maintainability": 90.0, "security": 85.0},
        "component_statuses": {"complexity": "success", "maintainability": "success", "security": "success"},
        "formula_version": "2.1",
    }
    _add_reduced_set_fields(old_hs)
    assert "score_validation" in old_hs
    assert old_hs["score_validation"]["validated"] is False
    assert old_hs["score_validation"]["basis"] == "heuristic weights not empirically validated"
    assert "analyzer_coverage" in old_hs
    assert old_hs["analyzer_coverage"]["components_analyzed"] == ["complexity", "maintainability", "security"]
    assert old_hs["analyzer_coverage"]["components_not_analyzed"] == []
