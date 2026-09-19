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

    assert status == "failed"
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
