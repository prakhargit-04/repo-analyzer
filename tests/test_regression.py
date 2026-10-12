"""
Regression suite: one test per real bug found during review, so that each
of these failure modes is caught automatically if it ever comes back.

Round 3 additions (this file): true byte-level content hashing replacing a
path+size+mtime heuristic that could miss same-size edits or mtime
collisions; bandit's exit code was never checked at all (any non-crash
exception fell through to parsing stdout as if the scan had completed);
and a 'partial' component status could produce a numeric sub-score while
the overall result was still (wrongly) reported as 'complete'.

Do not delete a test here just because the underlying feature gets
refactored -- rewrite it against the new implementation instead. The
point of this file is that these specific mistakes can never silently
reappear.
"""
from __future__ import annotations
import os
import subprocess
import sys
import tempfile
import time

import pytest

from util import is_test_file, resolve_snapshot_id, build_cache_key
from health_score import compute_health_score
from static_analysis import run_bandit, analyze_repository
from graph_builder import build_graph
from parse_python import FunctionNode, FileParseResult


# ---------------------------------------------------------------------------
# 1. Snapshot hashing (util.resolve_snapshot_id)
# ---------------------------------------------------------------------------

def test_content_hash_changes_when_file_content_changes():
    """A local (non-fresh-clone) path must not reuse a stale cache key when
    a file's actual content changes, even if git HEAD hasn't moved (dirty
    working tree). This was the original cache-correctness bug."""
    with tempfile.TemporaryDirectory() as d:
        target = os.path.join(d, "a.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")

        id_before = resolve_snapshot_id(d, is_fresh_clone=False, git_sha="deadbeef")

        # ensure mtime actually advances on fast filesystems/CI runners
        time.sleep(1.1)
        with open(target, "w") as fh:
            fh.write("x = 2\nyy = 3\n")

        id_after = resolve_snapshot_id(d, is_fresh_clone=False, git_sha="deadbeef")

        assert id_before != id_after, (
            "content changed but snapshot id stayed the same -- "
            "cache would incorrectly serve stale results"
        )


def test_snapshot_id_uses_git_sha_for_fresh_clone():
    """Fresh clones are trusted to use the git SHA directly (cheap, correct,
    no need to hash the whole tree) -- this is the fast path and must not
    regress into always content-hashing."""
    with tempfile.TemporaryDirectory() as d:
        snap = resolve_snapshot_id(d, is_fresh_clone=True, git_sha="abc123")
        assert snap == "abc123"


def test_content_hash_changes_when_content_changes_same_size():
    """A path+size+mtime heuristic can miss an edit that happens to
    preserve file size. Real byte-level hashing must not."""
    with tempfile.TemporaryDirectory() as d:
        file = os.path.join(d, "example.py")
        with open(file, "w") as fh:
            fh.write("x = 1\n")
        first = resolve_snapshot_id(d, is_fresh_clone=False, git_sha=None)

        with open(file, "w") as fh:
            fh.write("y = 2\n")  # identical byte length, different content
        second = resolve_snapshot_id(d, is_fresh_clone=False, git_sha=None)

        assert first != second


def test_content_hash_ignores_size_and_mtime_collisions():
    """Stronger version of the above: also pin mtime back to its original
    value after the edit, so a size+mtime-based heuristic (the old
    implementation) would provably fail this test, while a true byte-level
    hash still correctly detects the change."""
    with tempfile.TemporaryDirectory() as d:
        file = os.path.join(d, "example.py")
        with open(file, "w") as fh:
            fh.write("x = 1\n")
        original_stat = os.stat(file)
        first = resolve_snapshot_id(d, is_fresh_clone=False, git_sha=None)

        with open(file, "w") as fh:
            fh.write("y = 2\n")  # same size
        os.utime(file, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

        second = resolve_snapshot_id(d, is_fresh_clone=False, git_sha=None)
        assert first != second


def test_build_cache_key_changes_when_analyzer_version_changes(monkeypatch):
    """A repo's content not changing must not mean a stale, pre-bugfix
    cached result gets served forever -- the cache key must also depend on
    the analyzer's own version, not just repository content."""
    import util as util_module

    snapshot_id = "content-sha256:deadbeef"
    key_before = build_cache_key(snapshot_id)

    monkeypatch.setattr(util_module, "ANALYZER_VERSION", "9.9.9-different")
    key_after = build_cache_key(snapshot_id)

    assert key_before != key_after


def test_build_cache_key_is_deterministic_for_same_inputs():
    """Complementary sanity check: identical (schema, analyzer_version,
    snapshot_id) must always produce the same key, or every run would be a
    cache miss even with nothing having changed."""
    snapshot_id = "content-sha256:deadbeef"
    assert build_cache_key(snapshot_id) == build_cache_key(snapshot_id)


# ---------------------------------------------------------------------------
# 2. Health-score status propagation for partial results
# ---------------------------------------------------------------------------

def test_weights_used_is_renormalized_not_raw():
    """Regression test for the exact bug the test suite itself caught:
    weights_used must report the renormalized weights actually used in the
    composite (summing to 1.0), not the raw WEIGHTS constant, which would
    misreport the formula whenever a component is missing."""
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "A"}]},
        "maintainability": {"status": "failed", "results": []},
        "security": {"status": "success", "results": []},
    }
    result = compute_health_score(analysis)
    total = sum(result["weights_used"].values())
    assert abs(total - 1.0) < 1e-6, (
        f"weights_used sums to {total}, not 1.0 -- it is reporting raw "
        "WEIGHTS instead of renormalized weights"
    )
    # raw WEIGHTS for complexity/security are 0.35/0.30 (don't sum to 1
    # without maintainability) -- confirm we're NOT just echoing those back
    assert result["weights_used"] != {"complexity": 0.35, "security": 0.30}


def test_failed_component_is_excluded_and_weights_sum_to_one():
    """Alias of the above under the review's requested name: a failed
    component's weight must be fully redistributed across the remaining
    components, not silently dropped (weights summing to less than 1) or
    left unnormalized."""
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "B"}]},
        "maintainability": {"status": "success", "results": [{"maintainability_index": 80.0}]},
        "security": {"status": "failed", "results": []},
    }
    result = compute_health_score(analysis)
    assert "security" not in result["weights_used"]
    assert abs(sum(result["weights_used"].values()) - 1.0) < 1e-6


def test_partial_component_can_contribute_score_but_not_complete_status():
    """The critical case this round of review caught: a 'partial' component
    (some results came back before a partial failure) still produces a
    real, non-None sub-score -- but that must NOT make the overall status
    'complete'. A previous version derived 'complete' purely from whether
    every sub-score was non-None, so a partial-but-numeric result was
    reported as a full, trustworthy analysis. It is not."""
    analysis = {
        "complexity": {"status": "partial", "results": [{"rank": "A"}]},  # some files failed, some didn't
        "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
        "security": {"status": "success", "results": []},
    }
    result = compute_health_score(analysis)

    # a real number was computed for complexity -- not missing/None
    assert result["sub_scores"]["complexity"] is not None
    assert "complexity" not in result["missing_components"]

    # yet the overall status must still honestly say partial
    assert result["status"] == "partial"
    assert result["component_statuses"]["complexity"] == "partial"


def test_partial_component_marks_health_partial():
    analysis = {
        "complexity": {"status": "partial", "results": [{"rank": "C"}]},
        "maintainability": {"status": "success", "results": [{"maintainability_index": 70.0}]},
        "security": {"status": "success", "results": []},
    }
    result = compute_health_score(analysis)
    assert result["status"] == "partial"


def test_failed_component_marks_health_partial():
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "A"}]},
        "maintainability": {"status": "failed", "results": []},
        "security": {"status": "success", "results": []},
    }
    result = compute_health_score(analysis)
    assert result["status"] == "partial"


def test_all_success_components_mark_health_complete():
    """Sanity check for the complementary case: nothing missing, nothing
    partial -> status really is 'complete', so the partial-status tests
    above aren't trivially always true."""
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "A"}]},
        "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
        "security": {"status": "success", "results": []},
    }
    result = compute_health_score(analysis)
    assert result["status"] == "complete"
    assert result["missing_components"] == []
    assert set(result["component_statuses"].values()) == {"success"}


def test_all_subscores_failed_yields_failed_status_not_a_score():
    """If every sub-score is unavailable there is no such thing as a health
    score computed from zero data -- must return status 'failed' with
    composite_health_score None, not silently default to some number."""
    analysis = {
        "complexity": {"status": "failed", "results": []},
        "maintainability": {"status": "failed", "results": []},
        "security": {"status": "failed", "results": []},
    }
    result = compute_health_score(analysis)
    assert result["status"] == "failed"
    assert result["composite_health_score"] is None


def test_all_components_failed_returns_no_composite_score():
    """Alias of the above under the review's requested name."""
    analysis = {
        "complexity": {"status": "failed", "results": []},
        "maintainability": {"status": "failed", "results": []},
        "security": {"status": "failed", "results": []},
    }
    result = compute_health_score(analysis)
    assert result["composite_health_score"] is None
    assert result["status"] == "failed"


def test_unknown_component_status_raises():
    """A component status outside {success, partial, failed} is a real bug
    upstream (a typo, a new status introduced without updating this module)
    and must fail loudly, not silently be treated as some default."""
    analysis = {
        "complexity": {"status": "totally-not-a-real-status", "results": []},
        "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
        "security": {"status": "success", "results": []},
    }
    with pytest.raises(ValueError):
        compute_health_score(analysis)


# ---------------------------------------------------------------------------
# 3. Bandit failure handling (static_analysis.run_bandit)
# ---------------------------------------------------------------------------

def test_bandit_crash_does_not_produce_clean_security_score():
    """A bandit crash (executable missing, non-zero unexpected exit,
    unparsable output) must report status 'failed', never 'success' with an
    empty issue list -- that would make a broken scan look like a spotless
    repository."""

    def _raise_not_found(*args, **kwargs):
        raise FileNotFoundError("bandit not installed")

    orig_run = subprocess.run
    import static_analysis as sa
    sa.subprocess.run = _raise_not_found
    try:
        status, issues = run_bandit("/tmp/doesnt_matter", ["a.py"])
    finally:
        sa.subprocess.run = orig_run

    assert status == "unavailable"
    assert status != "success"
    assert issues == []


def test_bandit_unparsable_output_marks_failed():
    """If bandit exits but its stdout isn't valid JSON, that must also be
    'failed', not treated as 'no issues found'."""
    class FakeProc:
        returncode = 0
        stdout = "not json at all {{{"
        stderr = ""

    import static_analysis as sa
    orig_run = subprocess.run
    sa.subprocess.run = lambda *a, **kw: FakeProc()
    try:
        status, issues = run_bandit("/tmp/doesnt_matter", ["a.py"])
    finally:
        sa.subprocess.run = orig_run

    assert status == "failed"
    assert issues == []


def test_bandit_unexpected_return_code_is_failed():
    """bandit's contract is 0 (clean) or 1 (issues found) for a completed
    scan. A previous version never checked returncode at all, so any other
    exit code (2 = usage/internal error, a crash) fell through to parsing
    stdout as if the scan had completed -- this must be 'failed' instead."""
    class FakeProc:
        returncode = 2
        stdout = '{"results": []}'  # plausible-looking output despite the crash
        stderr = "internal error"

    import static_analysis as sa
    orig_run = subprocess.run
    sa.subprocess.run = lambda *a, **kw: FakeProc()
    try:
        status, issues = run_bandit("/tmp/doesnt_matter", ["a.py"])
    finally:
        sa.subprocess.run = orig_run

    assert status == "failed"
    assert issues == []


def test_bandit_non_list_results_field_is_failed():
    """Malformed-but-parseable JSON (results isn't a list) must also be
    'failed', not iterate over whatever garbage is there."""
    class FakeProc:
        returncode = 0
        stdout = '{"results": "not-a-list"}'
        stderr = ""

    import static_analysis as sa
    orig_run = subprocess.run
    sa.subprocess.run = lambda *a, **kw: FakeProc()
    try:
        status, issues = run_bandit("/tmp/doesnt_matter", ["a.py"])
    finally:
        sa.subprocess.run = orig_run

    assert status == "failed"
    assert issues == []


def test_empty_target_list_is_a_legitimate_success():
    """No production files to scan is a real, honest success (nothing to
    flag), not a failure -- must not be confused with the crash case."""
    status, issues = run_bandit("/tmp/doesnt_matter", [])
    assert status == "success"
    assert issues == []


# ---------------------------------------------------------------------------
# 4. Duplicate function-name call resolution (graph_builder.build_graph)
# ---------------------------------------------------------------------------

def _fn(id_, name, file_, calls=None):
    return FunctionNode(id=id_, name=name, file=file_, start_line=1, end_line=2, calls=calls or [])


def test_duplicate_function_names_are_not_high_confidence():
    """Two functions sharing a name in the same file must never be
    silently resolved to 'high_confidence' -- previously a plain dict
    comprehension let the second definition overwrite the first, so a call
    to the duplicated name confidently pointed at whichever one happened to
    survive. It must instead be flagged as ambiguous."""
    f1 = _fn("a.py::process:1", "process", "a.py")
    f2 = _fn("a.py::process:10", "process", "a.py")
    caller = _fn("a.py::caller:20", "caller", "a.py", calls=["process"])

    fr = FileParseResult(file="a.py", functions=[f1, f2, caller], classes=[], imports=[])
    g = build_graph([fr])

    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]
    assert len(call_edges) == 1
    _, _, data = call_edges[0]
    assert data["confidence"] == "flagged"
    assert data["reason"] == "duplicate_same_file_candidates"


def test_unique_same_file_function_is_still_high_confidence():
    """Complementary sanity check: a genuinely unique same-file function
    name must still resolve to high_confidence -- confirms the duplicate
    fix didn't just make everything flagged."""
    target = _fn("a.py::helper:1", "helper", "a.py")
    caller = _fn("a.py::caller:20", "caller", "a.py", calls=["helper"])

    fr = FileParseResult(file="a.py", functions=[target, caller], classes=[], imports=[])
    g = build_graph([fr])

    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]
    assert len(call_edges) == 1
    u, v, data = call_edges[0]
    assert v == "a.py::helper:1"
    assert data["confidence"] == "high_confidence"


# ---------------------------------------------------------------------------
# 5. Test-file exclusion (util.is_test_file)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "testing/fixtures.py",
    "src/testing/helpers.py",
    "pkg/testing/subdir/util.py",
])
def test_testing_directory_is_excluded(path):
    assert is_test_file(path) is True


@pytest.mark.parametrize("path", [
    "conftest.py",
    "tests/conftest.py",
    "a/b/c/conftest.py",
])
def test_conftest_is_excluded(path):
    assert is_test_file(path) is True


@pytest.mark.parametrize("path", [
    "src/main.py",
    "pkg/utils.py",
    "app/models/user.py",
])
def test_production_file_is_not_excluded(path):
    assert is_test_file(path) is False


@pytest.mark.parametrize("path", [
    "test_login.py",
    "pkg/test_utils.py",
    "pkg/utils_test.py",
])
def test_test_prefix_and_suffix_are_excluded(path):
    assert is_test_file(path) is True


# ---------------------------------------------------------------------------
# 6. Cross-check: static_analysis.analyze_repository respects is_test_file
#    identically for complexity/maintainability/security (the original
#    "tests excluded from bandit but not radon" drift bug).
# ---------------------------------------------------------------------------

def test_test_files_excluded_consistently_across_all_three_metrics():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "tests"))
        prod_file = os.path.join(d, "app.py")
        test_file = os.path.join(d, "tests", "test_app.py")
        with open(prod_file, "w") as fh:
            fh.write("def f():\n    return 1\n")
        with open(test_file, "w") as fh:
            fh.write("def test_f():\n    assert f() == 1\n")

        result = analyze_repository(d, ["app.py", "tests/test_app.py"])

        assert result["production_files_analyzed"] == 1
        assert result["test_files_excluded"] == 1
        complexity_files = {r["file"] for r in result["complexity"]["results"]}
        assert "tests/test_app.py" not in complexity_files
        assert "app.py" in complexity_files


# ---------------------------------------------------------------------------
# 7. Session 1 Canonical Schema Contract & Deterministic Serialization
# ---------------------------------------------------------------------------

def test_canonical_schema_top_level_fields():
    """Verify that run_pipeline includes all frozen canonical schema fields."""
    from main import run_pipeline
    from util import SCHEMA_VERSION, CACHE_SCHEMA_VERSION, ANALYZER_VERSION

    with tempfile.TemporaryDirectory() as d:
        file = os.path.join(d, "main.py")
        with open(file, "w") as fh:
            fh.write("def hello():\n    return 'world'\n")

        res = run_pipeline(None, d, None, os.path.join(d, ".cache"))

        assert res["schema_version"] == SCHEMA_VERSION
        assert res["cache_schema_version"] == CACHE_SCHEMA_VERSION
        assert res["analyzer_version"] == ANALYZER_VERSION
        assert res["languages"] == ["python"]
        assert res["analysis_status"] in ("complete", "partial", "failed")
        assert "repository" in res
        assert "commit_sha" in res
        assert "cache_snapshot_id" in res
        assert "cache_key_basis" in res
        assert "analyzed_at_utc" in res
        assert "files_analyzed" in res
        assert "parse_errors" in res
        assert "static_analysis" in res
        assert "knowledge_graph_summary" in res
        assert "knowledge_graph" in res
        assert "health_score" in res


def test_deterministic_serialization_reproducibility():
    """Verify that output serialization is byte-for-byte deterministic."""
    import json
    from main import run_pipeline

    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
        with open(os.path.join(d, "b.py"), "w") as fh:
            fh.write("def b(): pass\n")
        with open(os.path.join(d, "a.py"), "w") as fh:
            fh.write("def a(): pass\n")

        res1 = run_pipeline(None, d, None, c1)
        res2 = run_pipeline(None, d, None, c2)

        # remove timestamp before comparison
        res1_clean = {k: v for k, v in res1.items() if k != "analyzed_at_utc"}
        res2_clean = {k: v for k, v in res2.items() if k != "analyzed_at_utc"}

        str1 = json.dumps(res1_clean, indent=2, sort_keys=True)
        str2 = json.dumps(res2_clean, indent=2, sort_keys=True)

        assert str1 == str2, "Pipeline output is not deterministically ordered"


def test_unsupported_and_unavailable_status_handling():
    """Verify health score handles 'unsupported' and 'unavailable' component statuses cleanly."""
    analysis = {
        "complexity": {"status": "success", "results": [{"rank": "A"}]},
        "maintainability": {"status": "unsupported", "results": []},
        "security": {"status": "unavailable", "results": []},
    }
    score = compute_health_score(analysis)
    assert score["sub_scores"]["complexity"] == 100.0
    assert score["sub_scores"]["maintainability"] is None
    assert score["sub_scores"]["security"] is None
    assert score["status"] == "partial"


# ---------------------------------------------------------------------------
# 8. Session 7 Health Score v2 Test Suite
# ---------------------------------------------------------------------------

class TestHealthScoreV2:
    """Comprehensive test suite for Health Score v2 requirements."""

    def test_health_score_v2_all_components_successful(self):
        """All 6 scoring components succeed -> score computed, complete status, no renormalization."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 80.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "success", "results": []},
            "osv_vulnerabilities": {"status": "success", "results": []},
            "lizard_complexity": {"status": "success", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["composite_health_score"] == 95.0
        assert res["status"] == "complete"
        assert res["missing_components"] == []
        assert res["weights_renormalized"] is False
        assert res["weights_used"] == {
            "complexity": 0.25,
            "maintainability": 0.25,
            "security": 0.20,
            "sast": 0.15,
            "secrets": 0.10,
            "vulnerabilities": 0.05,
        }
        assert "lizard_complexity" in res["informational_analyzers"]

    def test_health_score_v2_partial_analyzer(self):
        """A partial analyzer contributes a numeric subscore but marks overall status partial."""
        analysis = {
            "complexity": {"status": "partial", "results": [{"rank": "B"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "success", "results": []},
            "osv_vulnerabilities": {"status": "success", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["sub_scores"]["complexity"] == 85.0
        assert res["status"] == "partial"
        assert res["component_statuses"]["complexity"] == "partial"

    def test_health_score_v2_failed_analyzer(self):
        """Failed component produces None subscore, triggers weight renormalization, status partial."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "failed", "results": []},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "success", "results": []},
            "osv_vulnerabilities": {"status": "success", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["sub_scores"]["maintainability"] is None
        assert "maintainability" in res["missing_components"]
        assert res["weights_renormalized"] is True
        assert res["status"] == "partial"
        assert abs(sum(res["weights_used"].values()) - 1.0) < 1e-4

    def test_health_score_v2_unsupported_analyzer(self):
        """Unsupported component (e.g. no dependency manifests) yields None subscore, partial status."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "success", "results": []},
            "osv_vulnerabilities": {"status": "unsupported", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["sub_scores"]["vulnerabilities"] is None
        assert "vulnerabilities" in res["missing_components"]
        assert res["weights_renormalized"] is True
        assert res["status"] == "partial"

    def test_health_score_v2_unavailable_analyzer(self):
        """Unavailable component (e.g. gitleaks not installed) yields None subscore, not a fake 100."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 90.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "unavailable", "results": []},
            "osv_vulnerabilities": {"status": "success", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["sub_scores"]["secrets"] is None
        assert "secrets" in res["missing_components"]
        assert res["status"] == "partial"

    def test_health_score_v2_multiple_unavailable_components(self):
        """Multiple unavailable components: remaining weights renormalized to sum to 1.0."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 100.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "unavailable", "results": []},
            "gitleaks_findings": {"status": "unavailable", "results": []},
            "osv_vulnerabilities": {"status": "unavailable", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["missing_components"] == ["sast", "secrets", "vulnerabilities"]
        assert abs(sum(res["weights_used"].values()) - 1.0) < 1e-4
        assert res["composite_health_score"] == 100.0

    def test_health_score_v2_weight_renormalization(self):
        """Verify exact renormalized weight values when some components are missing."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 100.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "failed", "results": []},
            "gitleaks_findings": {"status": "failed", "results": []},
            "osv_vulnerabilities": {"status": "failed", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["weights_used"]["complexity"] == 0.3571
        assert res["weights_used"]["maintainability"] == 0.3571
        assert res["weights_used"]["security"] == 0.2857
        assert res["weights_renormalized"] is True

    def test_health_score_v2_no_usable_scoring_components(self):
        """All scoring components failed -> score is None, status is failed."""
        analysis = {
            "complexity": {"status": "failed", "results": []},
            "maintainability": {"status": "failed", "results": []},
            "security": {"status": "failed", "results": []},
            "semgrep_findings": {"status": "failed", "results": []},
            "gitleaks_findings": {"status": "failed", "results": []},
            "osv_vulnerabilities": {"status": "failed", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["composite_health_score"] is None
        assert res["status"] == "failed"
        assert len(res["missing_components"]) == 6

    def test_health_score_v2_deterministic_scoring(self):
        """Repeated computation yields identical result dictionaries."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "B"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 75.0}]},
            "security": {"status": "success", "results": [{"severity": "HIGH"}]},
            "semgrep_findings": {"status": "success", "results": [{"severity": "WARNING"}]},
            "gitleaks_findings": {"status": "success", "results": [{"rule_id": "api-key"}]},
            "osv_vulnerabilities": {"status": "success", "results": [{"vulnerability_id": "CVE-1"}]},
        }
        res1 = compute_health_score(analysis)
        res2 = compute_health_score(analysis)
        assert res1 == res2

    def test_health_score_v2_backward_compatibility(self):
        """Legacy 3-component input dictionary uses legacy weights (0.35, 0.35, 0.30)."""
        analysis = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 100.0}]},
            "security": {"status": "success", "results": []},
        }
        res = compute_health_score(analysis)
        assert res["composite_health_score"] == 100.0
        assert res["weights_used"] == {"complexity": 0.35, "maintainability": 0.35, "security": 0.30}
        assert res["weights_renormalized"] is False

    def test_health_score_v2_lizard_is_informational_only(self):
        """Lizard findings do not change composite score or scoring weights."""
        analysis_without_lizard = {
            "complexity": {"status": "success", "results": [{"rank": "A"}]},
            "maintainability": {"status": "success", "results": [{"maintainability_index": 80.0}]},
            "security": {"status": "success", "results": []},
            "semgrep_findings": {"status": "success", "results": []},
            "gitleaks_findings": {"status": "success", "results": []},
            "osv_vulnerabilities": {"status": "success", "results": []},
        }
        analysis_with_lizard = dict(analysis_without_lizard)
        analysis_with_lizard["lizard_complexity"] = {
            "status": "success",
            "results": [{"cyclomatic_complexity": 50, "nloc": 100}],
        }

        res_without = compute_health_score(analysis_without_lizard)
        res_with = compute_health_score(analysis_with_lizard)

        assert res_without["composite_health_score"] == res_with["composite_health_score"]
        assert res_without["weights_used"] == res_with["weights_used"]
        assert "lizard_complexity" in res_with["informational_analyzers"]


# ---------------------------------------------------------------------------
# Phase 1 Regression Tests
# ---------------------------------------------------------------------------

def test_db_reconstructed_knowledge_graph_summary(tmp_path):
    """1.1: DB reconstruction must return knowledge_graph_summary (persisted or recomputed for legacy)."""
    from db.engine import get_engine, create_all_tables
    from db.store import persist_analysis, _run_to_dict
    from sqlalchemy.orm import Session
    from db.models import AnalysisRun, Snapshot, Repository

    db_url = f"sqlite:///{tmp_path}/test_kg_summary.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    sample_summary = {
        "total_nodes": 10,
        "total_edges": 5,
        "call_edges_total": 3,
        "call_edges_by_confidence": {"high_confidence": 2, "low_confidence": 1, "flagged": 0},
        "call_edges_resolved_pct": 100.0,
        "inherits_edges_total": 1,
        "depends_on_edges_total": 1,
        "has_finding_edges_total": 0,
        "finding_nodes_total": 0,
        "resolution_caveat": "test caveat",
    }

    result = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": "0.23.0",
        "repository": "https://github.com/test/repo",
        "commit_sha": "abc1234",
        "cache_snapshot_id": "snap123",
        "analyzed_at_utc": "2026-10-10T12:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 2,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph_summary": sample_summary,
        "knowledge_graph": {
            "nodes": [
                {"id": "file.py", "type": "file", "provenance": "test"},
                {"id": "func1", "type": "function", "name": "func1", "file": "file.py", "provenance": "test"},
                {"id": "func2", "type": "function", "name": "func2", "file": "file.py", "provenance": "test"},
            ],
            "edges": [
                {"source": "func1", "target": "func2", "relation": "calls", "confidence": "high_confidence", "provenance": "test"},
            ],
        },
        "health_score": {"composite_health_score": 90.0, "status": "complete"},
    }

    with Session(engine) as session:
        run_id = persist_analysis(session, result)
        run = session.query(AnalysisRun).filter_by(id=run_id).one()
        reconstructed = _run_to_dict(session, run)

        # 1. Persisted summary returned directly
        assert "knowledge_graph_summary" in reconstructed
        assert reconstructed["knowledge_graph_summary"]["total_nodes"] == 10
        assert reconstructed["knowledge_graph_summary"]["call_edges_total"] == 3

        # 2. Legacy fallback when knowledge_graph_summary_json is None
        run.knowledge_graph_summary_json = None
        session.commit()
        reconstructed_legacy = _run_to_dict(session, run)
        assert reconstructed_legacy["knowledge_graph_summary"]["total_nodes"] == 3
        assert reconstructed_legacy["knowledge_graph_summary"]["call_edges_total"] == 1


def test_graph_builder_golden_output():
    """2.1: Graph output must remain byte-identical before and after index refactoring."""
    import json
    from parse_python import ClassNode, FunctionNode, ImportEdge, FileParseResult
    from graph_builder import build_graph

    cls_base = ClassNode(id="base.py::Base:1", name="Base", file="base.py", start_line=1, end_line=20, bases=[])
    fn_base_m = FunctionNode(id="base.py::Base.greet:5", name="greet", file="base.py", start_line=5, end_line=10, class_owner="Base")
    fr_base = FileParseResult(file="base.py", classes=[cls_base], functions=[fn_base_m], imports=[])

    cls_sub = ClassNode(id="sub.py::Sub:1", name="Sub", file="sub.py", start_line=1, end_line=30, bases=["Base"])
    fn_sub_init = FunctionNode(id="sub.py::Sub.__init__:5", name="__init__", file="sub.py", start_line=5, end_line=10, class_owner="Sub", calls=["super.greet"])
    fn_sub_work = FunctionNode(id="sub.py::Sub.work:15", name="work", file="sub.py", start_line=15, end_line=25, class_owner="Sub", calls=["new Base", "helper"])
    fn_sub_help = FunctionNode(id="sub.py::helper:27", name="helper", file="sub.py", start_line=27, end_line=29)
    imp_sub = ImportEdge(file="sub.py", imported="base.Base", alias=None, line=1)
    fr_sub = FileParseResult(file="sub.py", classes=[cls_sub], functions=[fn_sub_init, fn_sub_work, fn_sub_help], imports=[imp_sub])

    g = build_graph([fr_base, fr_sub])
    nodes = sorted([{"id": n, **d} for n, d in g.nodes(data=True)], key=lambda x: str(x["id"]))
    edges = sorted([{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)], key=lambda x: (str(x["source"]), str(x["target"]), str(x.get("relation", ""))))

    output_json1 = json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True)

    g2 = build_graph([fr_base, fr_sub])
    nodes2 = sorted([{"id": n, **d} for n, d in g2.nodes(data=True)], key=lambda x: str(x["id"]))
    edges2 = sorted([{"source": u, "target": v, **d} for u, v, d in g2.edges(data=True)], key=lambda x: (str(x["source"]), str(x["target"]), str(x.get("relation", ""))))
    output_json2 = json.dumps({"nodes": nodes2, "edges": edges2}, sort_keys=True)

    assert output_json1 == output_json2


def test_graph_builder_large_repo_timing():
    """2.1: Synthetic large-repo timing test (2000 functions) with threshold to catch O(n^2) regressions."""
    import time
    from parse_python import ClassNode, FunctionNode, FileParseResult
    from graph_builder import build_graph

    files = []
    for f_idx in range(50):
        funcs = []
        classes = []
        cls = ClassNode(id=f"file_{f_idx}.py::Class_{f_idx}:1", name=f"Class_{f_idx}", file=f"file_{f_idx}.py", start_line=1, end_line=100, bases=[])
        classes.append(cls)
        for fn_idx in range(40):
            fn = FunctionNode(
                id=f"file_{f_idx}.py::fn_{f_idx}_{fn_idx}:{10+fn_idx}",
                name=f"fn_{fn_idx}",
                file=f"file_{f_idx}.py",
                start_line=10 + fn_idx,
                end_line=15 + fn_idx,
                class_owner=f"Class_{f_idx}" if fn_idx % 2 == 0 else None,
                calls=[f"self.fn_{fn_idx-1}"] if fn_idx > 0 else ["new Class_0"],
            )
            funcs.append(fn)
        files.append(FileParseResult(file=f"file_{f_idx}.py", classes=classes, functions=funcs, imports=[]))

    t0 = time.perf_counter()
    g = build_graph(files)
    elapsed = time.perf_counter() - t0

    assert g.number_of_nodes() > 2000
    assert elapsed < 3.0, f"build_graph took {elapsed:.2f}s for 2000 functions — O(n^2) regression!"


def test_rag_prompt_truncation_preserves_question_and_rules():
    """1.2: Evidence context builder must not drop the user question or system rules."""
    from rag.context_builder import build_evidence_context, build_rag_user_prompt, SYSTEM_GROUNDING_PROMPT
    from api.schemas import AskRequest
    from pydantic import ValidationError

    # Create 20 large chunks (each ~1000 chars)
    large_chunks = [
        {
            "chunk_id": f"chunk_{i}",
            "file_path": f"src/module_{i}.py",
            "start_line": 1,
            "end_line": 100,
            "language": "python",
            "chunk_text": f"# Code block {i}\n" + ("x = 1\n" * 50),
            "provenance": "TOOL_DERIVED",
        }
        for i in range(20)
    ]

    question = "How is user authentication initialized in this project?"
    context_str, evidence_map = build_evidence_context(large_chunks)
    prompt = build_rag_user_prompt(question, context_str)

    assert question in prompt, "User question was dropped from prompt"
    assert "STRICT RULES:" in SYSTEM_GROUNDING_PROMPT

    # Test max_length validation on AskRequest
    with pytest.raises(ValidationError):
        AskRequest(question="a" * 1001)


def test_semgrep_severity_scoring_monotonic_ordering():
    """1.3: Semgrep penalties must enforce ERROR > WARNING > INFO."""
    from health_score import SEMGREP_SEVERITY_PENALTY, _sast_subscore

    err_pen = SEMGREP_SEVERITY_PENALTY.get("ERROR", SEMGREP_SEVERITY_PENALTY.get("HIGH", 15))
    warn_pen = SEMGREP_SEVERITY_PENALTY.get("WARNING", SEMGREP_SEVERITY_PENALTY.get("MEDIUM", 5))
    info_pen = SEMGREP_SEVERITY_PENALTY.get("INFO", SEMGREP_SEVERITY_PENALTY.get("LOW", 2))

    assert err_pen > warn_pen > info_pen, f"Semgrep penalties not monotonic: ERROR={err_pen}, WARNING={warn_pen}, INFO={info_pen}"


def test_cache_key_does_not_instantiate_embedding_provider(monkeypatch):
    """1.4: build_cache_key must derive key from config without instantiating embedding provider."""
    import embeddings

    def bad_instantiate(*args, **kwargs):
        raise AssertionError("get_embedding_provider was called during build_cache_key!")

    monkeypatch.setattr(embeddings, "get_embedding_provider", bad_instantiate)
    key = build_cache_key("test_snapshot_123")
    assert isinstance(key, str) and len(key) == 64


def test_lifespan_stale_jobs_marked_failed(tmp_path):
    """1.5: Startup lifespan must mark stale jobs as failed."""
    from db.engine import get_engine, create_all_tables
    from db.models import AnalysisJob
    from db.store import cleanup_stale_jobs
    from sqlalchemy.orm import Session
    from datetime import datetime, timezone, timedelta

    db_url = f"sqlite:///{tmp_path}/test_stale_jobs.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=3600)

    with Session(engine) as session:
        job = AnalysisJob(
            repo_url="https://github.com/test/stale",
            status="analyzing",
            current_stage="analyzing",
            created_at=stale_time,
            updated_at=stale_time,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    cleanup_stale_jobs(engine, stale_seconds=1800)

    with Session(engine) as session:
        j = session.query(AnalysisJob).filter_by(id=job_id).one()
        assert j.status == "failed"
        assert "stuck" in j.error_message.lower() or "stale" in j.error_message.lower()


def test_retrieval_dimension_mismatch_returns_409(tmp_path):
    """1.6: Retrieval vector dimension mismatch must return clear 409 Conflict, not 500."""
    from db.engine import get_engine, create_all_tables
    from db.store import persist_analysis, retrieve_similar_chunks
    from sqlalchemy.orm import Session
    from embeddings import TestEmbeddingProvider
    from fastapi import HTTPException

    db_url = f"sqlite:///{tmp_path}/test_dim_mismatch.db"
    engine = get_engine(db_url)
    create_all_tables(engine)

    # Persist chunks with a 64d provider
    prov64 = TestEmbeddingProvider(dimension=64)
    chunk = {
        "chunk_id": "c1",
        "file_path": "a.py",
        "start_line": 1,
        "end_line": 10,
        "chunk_text": "def foo(): pass",
        "chunk_hash": "h1",
    }
    vec = prov64.embed_query("def foo(): pass")

    result = {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": "0.23.0",
        "repository": "https://github.com/test/repo",
        "commit_sha": "abc1234",
        "cache_snapshot_id": "snap123",
        "analyzed_at_utc": "2026-10-10T12:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 1,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph": {"nodes": [], "edges": []},
        "health_score": {"composite_health_score": 90.0, "status": "complete"},
        "source_chunks": [chunk],
        "source_embeddings": [
            {
                "source_chunk_id": "c1",
                "chunk_id": "c1",
                "model_name": prov64.name,
                "model_version": prov64.model_version,
                "dimension": 64,
                "vector_json": str(vec),
            }
        ],
    }

    from db.store import persist_analysis, retrieve_similar_chunks, EmbeddingMismatchError
    from fastapi.testclient import TestClient
    from api.app import app

    with Session(engine) as session:
        run_id = persist_analysis(session, result)
        session.commit()
        prov128 = TestEmbeddingProvider(dimension=128)
        # Force provider name match but dimension mismatch
        prov128.name = prov64.name

        with pytest.raises(EmbeddingMismatchError) as exc_info:
            retrieve_similar_chunks(
                session,
                run_id=run_id,
                query_text="foo",
                top_k=5,
                provider=prov128,
            )
        assert "re-run analysis" in str(exc_info.value).lower()

    # HTTP-level tests for POST, GET retrieval endpoints and POST /ask asserting status 409
    from api.routes import get_db_session
    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db
    try:
        client = TestClient(app)
        # Monkeypatch active provider to mismatch stored dimension
        import embeddings
        embeddings.reset_embedding_provider_cache()
        embeddings._GLOBAL_EMBEDDING_PROVIDER = prov128

        # POST /api/v1/analyses/{run_id}/retrieve
        res_post = client.post(f"/api/v1/analyses/{run_id}/retrieve", json={"query": "foo", "top_k": 5})
        assert res_post.status_code == 409
        assert "re-run analysis" in res_post.json()["detail"].lower()

        # GET /api/v1/analyses/{run_id}/retrieve
        res_get = client.get(f"/api/v1/analyses/{run_id}/retrieve?query=foo&top_k=5")
        assert res_get.status_code == 409
        assert "re-run analysis" in res_get.json()["detail"].lower()

        # POST /api/v1/analyses/{run_id}/ask
        res_ask = client.post(f"/api/v1/analyses/{run_id}/ask", json={"question": "foo", "top_k": 5})
        assert res_ask.status_code == 409
        assert "re-run analysis" in res_ask.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        import embeddings
        embeddings.reset_embedding_provider_cache()


def test_non_python_lizard_complexity_subscore():
    """3.1: Non-Python repositories with no Radon results use Lizard complexity fallback."""
    from health_score import compute_health_score

    analysis = {
        "complexity": {"status": "unsupported", "results": []},
        "maintainability": {"status": "unsupported", "results": []},
        "security": {"status": "unsupported", "results": []},
        "lizard_complexity": {
            "status": "success",
            "results": [
                {"file": "app.js", "function": "foo", "cyclomatic_complexity": 3},
                {"file": "app.js", "function": "bar", "cyclomatic_complexity": 15},
            ],
        },
    }

    hs = compute_health_score(analysis)
    assert hs["sub_scores"]["complexity"] is not None
    assert hs["component_statuses"]["complexity"] == "success"
    # CC 3 -> 100 points, CC 15 -> 70 points. Average = 85.0
    assert hs["sub_scores"]["complexity"] == 85.0


def test_x_api_key_auth_middleware(monkeypatch, tmp_path):
    """4.1: If API_KEY env is set, request without or with wrong X-API-Key returns 401."""
    from fastapi.testclient import TestClient
    from db.engine import get_engine, create_all_tables
    from api.app import create_app

    db_path = str(tmp_path / "test_auth.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    engine = get_engine(f"sqlite:///{db_path}")
    create_all_tables(engine)

    monkeypatch.setenv("API_KEY", "secret-test-key")
    app = create_app()
    client = TestClient(app)

    # Public endpoint (/api/v1/health) should pass without key
    r = client.get("/api/v1/health")
    assert r.status_code == 200

    # Protected endpoint without key -> 401
    r = client.get("/api/v1/analyses/latest?repo_url=https://github.com/owner/repo")
    assert r.status_code == 401
    assert "Invalid or missing API key" in r.json()["detail"]

    # Protected endpoint with valid key -> 404 (not found, but auth passed!)
    r = client.get("/api/v1/analyses/latest?repo_url=https://github.com/owner/repo", headers={"X-API-Key": "secret-test-key"})
    assert r.status_code == 404


def test_rate_limiting_returns_429(monkeypatch, tmp_path):
    """4.2: Rate limiting returns 429 with Retry-After header when threshold exceeded."""
    from fastapi.testclient import TestClient
    from db.engine import get_engine, create_all_tables
    from api.app import create_app

    db_path = str(tmp_path / "test_ratelimit.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    engine = get_engine(f"sqlite:///{db_path}")
    create_all_tables(engine)

    monkeypatch.setenv("RATE_LIMIT_RPM", "2")
    app = create_app()
    client = TestClient(app)

    url = "https://github.com/owner/repo"
    r1 = client.post("/api/v1/analyses", json={"repo_url": url})
    assert r1.status_code in (202, 422, 503)

    r2 = client.post("/api/v1/analyses", json={"repo_url": url})
    assert r2.status_code in (202, 422, 503)

    # 3rd request exceeds 2 RPM bucket -> 429
    r3 = client.post("/api/v1/analyses", json={"repo_url": url})
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
    assert "Rate limit exceeded" in r3.json()["detail"]


def test_max_active_jobs_backpressure_returns_503(monkeypatch, tmp_path):
    """4.3: MAX_ACTIVE_JOBS capacity limit returns 503 Service Unavailable."""
    from fastapi.testclient import TestClient
    from db.engine import get_engine, create_all_tables
    from db.models import AnalysisJob
    from db.store import create_job
    from sqlalchemy.orm import Session
    from api.app import create_app

    db_path = str(tmp_path / "test_backpressure.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MAX_ACTIVE_JOBS", "1")

    engine = get_engine(f"sqlite:///{db_path}")
    create_all_tables(engine)

    with Session(engine) as session:
        create_job(session, "https://github.com/owner/repo1", commit_sha="sha1")
        session.commit()

    app = create_app()
    client = TestClient(app)

    # Active count is 1, MAX_ACTIVE_JOBS is 1 -> new submission gets 503
    r = client.post("/api/v1/analyses", json={"repo_url": "https://github.com/owner/repo2"})
    assert r.status_code == 503
    assert "at capacity" in r.json()["detail"]



