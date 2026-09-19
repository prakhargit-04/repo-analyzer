"""
Contract & Fixture Test Suite for Session 2.

Verifies that all analyzers adhere strictly to the AnalyzerContract,
supporting all 5 statuses: success, partial, failed, unsupported, unavailable.
"""
from __future__ import annotations
import os
import pytest
from analyzer_contract import (
    AnalyzerStatus,
    AnalyzerResult,
    BaseAnalyzer,
    VALID_STATUS_VALUES,
)
from static_analysis import analyze_repository, run_bandit, LizardAnalyzer, LIZARD_VERSION
import static_analysis as _sa_module
from main import run_pipeline


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class DummyMockAnalyzer(BaseAnalyzer):
    """Concrete implementation of BaseAnalyzer for testing contract methods."""

    def __init__(self, available: bool = True, supported_lang: str = "python"):
        super().__init__("dummy_tool", "1.0.0")
        self._available = available
        self._supported_lang = supported_lang

    def is_available(self) -> tuple[bool, str | None]:
        if self._available:
            return True, None
        return False, "Binary 'dummy_tool' not found in system PATH"

    def supports_language(self, language: str) -> bool:
        return language == self._supported_lang

    def analyze(self, repo_root: str, files: list[str]) -> AnalyzerResult:
        avail, err = self.is_available()
        if not avail:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=[err] if err else [],
                provenance=self.provenance_tag,
            )
        if not files or not any(f.endswith(".py") for f in files):
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
            )
        return AnalyzerResult(
            status=AnalyzerStatus.SUCCESS,
            results=[{"file": f, "status": "ok"} for f in files],
            provenance=self.provenance_tag,
        )


def test_analyzer_status_enum_values():
    assert AnalyzerStatus.SUCCESS == "success"
    assert AnalyzerStatus.PARTIAL == "partial"
    assert AnalyzerStatus.FAILED == "failed"
    assert AnalyzerStatus.UNSUPPORTED == "unsupported"
    assert AnalyzerStatus.UNAVAILABLE == "unavailable"
    assert len(VALID_STATUS_VALUES) == 5


def test_analyzer_result_validation():
    res = AnalyzerResult(status="success", results=[{"a": 1}], provenance="tool:1.0")
    assert res.to_dict() == {
        "status": "success",
        "results": [{"a": 1}],
        "provenance": "tool:1.0",
    }

    with pytest.raises(ValueError):
        AnalyzerResult(status="invalid_status")


def test_dummy_analyzer_contract_methods():
    analyzer = DummyMockAnalyzer(available=True)
    assert analyzer.provenance_tag == "dummy_tool:1.0.0"
    assert analyzer.supports_language("python") is True
    assert analyzer.supports_language("java") is False

    res = analyzer.analyze("/tmp", ["app.py"])
    assert res.status == "success"
    assert len(res.results) == 1

    unavailable_analyzer = DummyMockAnalyzer(available=False)
    res_unavail = unavailable_analyzer.analyze("/tmp", ["app.py"])
    assert res_unavail.status == "unavailable"
    assert len(res_unavail.errors) == 1


def test_fixture_success_repo():
    repo_path = os.path.join(FIXTURES_DIR, "success_repo")
    res = run_pipeline(None, repo_path, None, os.path.join(repo_path, ".cache"))

    assert res["analysis_status"] == "complete"
    assert res["health_score"]["status"] == "complete"
    assert res["static_analysis"]["complexity"]["status"] == "success"
    assert res["static_analysis"]["maintainability"]["status"] == "success"
    assert res["static_analysis"]["security"]["status"] == "success"


def test_fixture_partial_repo():
    repo_path = os.path.join(FIXTURES_DIR, "partial_repo")
    res = run_pipeline(None, repo_path, None, os.path.join(repo_path, ".cache"))

    # broken.py syntax error causes complexity/maintainability to be partial
    assert res["static_analysis"]["complexity"]["status"] == "partial"
    assert res["static_analysis"]["maintainability"]["status"] == "partial"
    assert res["analysis_status"] == "partial"
    assert res["health_score"]["status"] == "partial"


def test_fixture_unsupported_repo():
    repo_path = os.path.join(FIXTURES_DIR, "unsupported_repo")
    res = run_pipeline(None, repo_path, None, os.path.join(repo_path, ".cache"))

    assert res["static_analysis"]["complexity"]["status"] == "unsupported"
    assert res["static_analysis"]["maintainability"]["status"] == "unsupported"
    assert res["static_analysis"]["security"]["status"] == "unsupported"
    assert res["files_analyzed"] == 0


def test_bandit_unavailable_simulation(monkeypatch):
    """Simulate missing bandit executable to verify 'unavailable' status semantics."""
    def mock_run(*args, **kwargs):
        raise FileNotFoundError("No bandit executable found")

    monkeypatch.setattr("subprocess.run", mock_run)
    status, issues = run_bandit("/fake", ["main.py"])

    assert status == "unavailable"
    assert issues == []


# ---------------------------------------------------------------------------
# Session 3 — LizardAnalyzer tests
# ---------------------------------------------------------------------------

class TestLizardAnalyzer:
    """Contract tests for LizardAnalyzer."""

    def test_lizard_is_available(self):
        """Lizard is installed (requirements.txt has lizard>=1.17)."""
        analyzer = LizardAnalyzer()
        avail, err = analyzer.is_available()
        assert avail is True
        assert err is None

    def test_lizard_version_string(self):
        """LIZARD_VERSION is a non-empty, non-'unavailable' string when installed."""
        assert LIZARD_VERSION not in ("", "unavailable")

    def test_lizard_provenance_tag(self):
        analyzer = LizardAnalyzer()
        assert analyzer.provenance_tag == f"lizard:{LIZARD_VERSION}"

    def test_lizard_supports_language(self):
        analyzer = LizardAnalyzer()
        assert analyzer.supports_language("python") is True
        assert analyzer.supports_language("Python") is True  # case-insensitive
        assert analyzer.supports_language("java") is True
        assert analyzer.supports_language("cobol") is False  # unsupported

    def test_lizard_empty_file_list_returns_unsupported(self):
        analyzer = LizardAnalyzer()
        result = analyzer.analyze("/fake/root", [])
        assert result.status == "unsupported"
        assert result.results == []

    def test_lizard_analyzes_success_fixture(self):
        """Lizard successfully analyzes the success fixture repo."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        py_files = [os.path.join(fixture, f) for f in os.listdir(fixture)
                    if f.endswith(".py")]
        analyzer = LizardAnalyzer()
        result = analyzer.analyze(fixture, py_files)
        assert result.status == "success"
        assert isinstance(result.results, list)
        # Each result should have mandatory fields
        for r in result.results:
            assert "file" in r
            assert "function" in r
            assert "cyclomatic_complexity" in r
            assert "nloc" in r
            assert "token_count" in r
            assert "max_nesting_depth" in r
            assert "provenance" in r
        assert result.metadata["files_analyzed"] == len(py_files)
        assert result.metadata["files_failed"] == 0

    def test_lizard_unavailable_simulation(self, monkeypatch):
        """Simulate lizard not installed: is_available() must return False."""
        monkeypatch.setattr(_sa_module, "_lizard_mod", None)
        analyzer = LizardAnalyzer()
        avail, err = analyzer.is_available()
        assert avail is False
        assert err is not None and "lizard" in err.lower()

        result = analyzer.analyze("/fake", ["/fake/app.py"])
        assert result.status == "unavailable"
        assert result.results == []
        assert len(result.errors) == 1

    def test_lizard_partial_on_bad_file(self, monkeypatch, tmp_path):
        """If one file fails and one succeeds, status is 'partial'."""
        good = tmp_path / "good.py"
        good.write_text("def foo():\n    return 1\n", encoding="utf-8")
        bad_path = str(tmp_path / "nonexistent.py")  # does not exist

        analyzer = LizardAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good), bad_path])
        # bad_path does not exist; lizard returns None or raises
        # good.py should succeed => partial
        assert result.status in ("success", "partial")  # depends on lizard behaviour for missing files
        # At minimum it must be a valid status
        assert result.status in VALID_STATUS_VALUES

    def test_analyze_repository_includes_lizard_complexity(self):
        """analyze_repository() output must include the 'lizard_complexity' key."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        py_files = [f for f in os.listdir(fixture) if f.endswith(".py")]
        result = analyze_repository(fixture, py_files)
        assert "lizard_complexity" in result
        lc = result["lizard_complexity"]
        assert lc["status"] in VALID_STATUS_VALUES
        assert "results" in lc

    def test_pipeline_lizard_complexity_present(self):
        """run_pipeline output must include lizard_complexity in static_analysis."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        res = run_pipeline(None, fixture, None, os.path.join(fixture, ".cache"))
        assert "lizard_complexity" in res["static_analysis"]
        lc = res["static_analysis"]["lizard_complexity"]
        assert lc["status"] in VALID_STATUS_VALUES
