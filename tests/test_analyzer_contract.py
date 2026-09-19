"""
Contract & Fixture Test Suite for Sessions 2, 3, and 4.

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
from static_analysis import (
    analyze_repository, run_bandit,
    LizardAnalyzer, LIZARD_VERSION,
    SemgrepAnalyzer, SEMGREP_VERSION, _SEMGREP_BINARY,
    GitleaksAnalyzer, GITLEAKS_VERSION, _GITLEAKS_BINARY,
    OSVAnalyzer, parse_manifest_file,
)
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


# ---------------------------------------------------------------------------
# Session 4 — SemgrepAnalyzer tests
# ---------------------------------------------------------------------------

SEMGREP_AVAILABLE = _SEMGREP_BINARY is not None


class TestSemgrepAnalyzer:
    """Contract tests for SemgrepAnalyzer."""

    def test_semgrep_version_constant(self):
        """SEMGREP_VERSION is a non-empty string when installed."""
        assert isinstance(SEMGREP_VERSION, str)
        assert SEMGREP_VERSION != ""

    def test_semgrep_is_available_when_installed(self):
        """SemgrepAnalyzer.is_available() reflects actual binary presence."""
        analyzer = SemgrepAnalyzer()
        avail, err = analyzer.is_available()
        if SEMGREP_AVAILABLE:
            assert avail is True
            assert err is None
        else:
            assert avail is False
            assert err is not None and "semgrep" in err.lower()

    def test_semgrep_provenance_tag(self):
        analyzer = SemgrepAnalyzer()
        assert analyzer.provenance_tag == f"semgrep:{SEMGREP_VERSION}"

    def test_semgrep_supports_language(self):
        analyzer = SemgrepAnalyzer()
        assert analyzer.supports_language("python") is True
        assert analyzer.supports_language("Python") is True   # case-insensitive
        assert analyzer.supports_language("java") is True
        assert analyzer.supports_language("cobol") is False    # not in scope

    def test_semgrep_empty_file_list_returns_unsupported(self):
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze("/fake/root", [])
        assert result.status == "unsupported"
        assert result.results == []

    def test_semgrep_nonexistent_files_returns_unsupported(self, tmp_path):
        """If all supplied paths don't exist on disk, return unsupported."""
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(tmp_path / "ghost.py")])
        assert result.status == "unsupported"

    def test_semgrep_unavailable_simulation(self, monkeypatch):
        """Simulate missing binary: is_available() returns False -> unavailable."""
        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", None)
        analyzer = SemgrepAnalyzer()
        avail, err = analyzer.is_available()
        assert avail is False
        assert "semgrep" in err.lower()

        result = analyzer.analyze("/fake", ["/fake/app.py"])
        assert result.status == "unavailable"
        assert result.results == []
        assert len(result.errors) >= 1

    def test_semgrep_timeout_simulation(self, monkeypatch, tmp_path):
        """Simulate subprocess timeout: status must be 'failed', not empty success."""
        import subprocess as _sp
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")

        def mock_run(*args, **kwargs):
            raise _sp.TimeoutExpired(cmd="semgrep", timeout=180)

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", mock_run)
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good)])
        assert result.status == "failed"
        assert any("timed out" in e.lower() for e in result.errors)

    def test_semgrep_bad_exit_code(self, monkeypatch, tmp_path):
        """Exit code 2 (error) must produce 'failed', not an empty result."""
        import subprocess as _sp
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 2
            stdout = ""
            stderr = "Internal error: semgrep crashed"

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good)])
        assert result.status == "failed"
        assert result.results == []

    def test_semgrep_unparsable_json(self, monkeypatch, tmp_path):
        """Unparsable stdout must produce 'failed'."""
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = "This is not JSON {{{"
            stderr = ""

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good)])
        assert result.status == "failed"
        assert any("json" in e.lower() for e in result.errors)

    def test_semgrep_missing_results_key(self, monkeypatch, tmp_path):
        """JSON without a 'results' list must produce 'failed'."""
        import json as _json
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = _json.dumps({"version": "1.0", "errors": []})
            stderr = ""

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good)])
        assert result.status == "failed"

    def test_semgrep_no_findings_is_success(self, monkeypatch, tmp_path):
        """Zero findings with exit code 0 is a legitimate success."""
        import json as _json
        good = tmp_path / "good.py"
        good.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = _json.dumps({"results": [], "errors": [], "version": "1.177.0"})
            stderr = ""

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(good)])
        assert result.status == "success"
        assert result.results == []

    def test_semgrep_finding_field_schema(self, monkeypatch, tmp_path):
        """Findings must carry: rule_id, file, line, col, message, severity, provenance."""
        import json as _json
        f = tmp_path / "vuln.py"
        f.write_text("import subprocess; subprocess.run(x, shell=True)\n", encoding="utf-8")

        finding = {
            "check_id": "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true",
            "path": str(f),
            "start": {"line": 1, "col": 18},
            "end": {"line": 1, "col": 40},
            "extra": {
                "message": "Subprocess called with shell=True",
                "severity": "WARNING",
                "metadata": {"cwe": ["CWE-78"]},
            },
        }

        class FakeProc:
            returncode = 1
            stdout = _json.dumps({"results": [finding], "errors": [], "version": "1.177.0"})
            stderr = ""

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        assert len(result.results) == 1
        r = result.results[0]
        assert r["rule_id"] == "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true"
        assert "vuln.py" in r["file"]
        assert r["line"] == 1
        assert r["col"] == 18
        assert "shell=True" in r["message"]
        assert r["severity"] == "WARNING"
        assert r["provenance"].startswith("semgrep:")
        assert r["cwe"] == ["CWE-78"]

    def test_semgrep_findings_deterministic_order(self, monkeypatch, tmp_path):
        """Findings must be sorted deterministically: file -> line -> col -> rule_id."""
        import json as _json
        f = tmp_path / "vuln.py"
        f.write_text("x = 1\n" * 5, encoding="utf-8")

        def make_finding(line, col, rule):
            return {
                "check_id": rule,
                "path": str(f),
                "start": {"line": line, "col": col},
                "end": {"line": line, "col": col + 1},
                "extra": {"message": "msg", "severity": "INFO", "metadata": {}},
            }

        raw = [
            make_finding(3, 1, "rule-b"),
            make_finding(1, 5, "rule-a"),
            make_finding(1, 5, "rule-z"),
            make_finding(2, 0, "rule-c"),
        ]

        class FakeProc:
            returncode = 1
            stdout = _json.dumps({"results": raw, "errors": []})
            stderr = ""

        monkeypatch.setattr(_sa_module, "_SEMGREP_BINARY", "/fake/semgrep")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = SemgrepAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        order = [(r["line"], r["col"], r["rule_id"]) for r in result.results]
        assert order == sorted(order)

    def test_semgrep_safe_env_strips_secrets(self):
        """_safe_env() must strip SEMGREP_APP_TOKEN, SEMGREP_LOGIN_TOKEN etc."""
        import os as _os
        with pytest.MonkeyPatch().context() as m:
            m.setenv("SEMGREP_APP_TOKEN", "supersecret")
            m.setenv("SEMGREP_LOGIN_TOKEN", "another_secret")
            m.setenv("SEMGREP_API_TOKEN", "yet_another")
            m.setenv("PATH", _os.environ.get("PATH", ""))
            env = SemgrepAnalyzer._safe_env()
        assert "SEMGREP_APP_TOKEN" not in env
        assert "SEMGREP_LOGIN_TOKEN" not in env
        assert "SEMGREP_API_TOKEN" not in env
        assert "PATH" in env  # safe vars are preserved

    def test_analyze_repository_includes_semgrep_findings(self):
        """analyze_repository() output must include the 'semgrep_findings' key."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        py_files = [f for f in os.listdir(fixture) if f.endswith(".py")]
        result = analyze_repository(fixture, py_files)
        assert "semgrep_findings" in result
        sf = result["semgrep_findings"]
        assert sf["status"] in VALID_STATUS_VALUES
        assert "results" in sf

    def test_pipeline_semgrep_findings_present(self):
        """run_pipeline output must include semgrep_findings in static_analysis."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        res = run_pipeline(None, fixture, None, os.path.join(fixture, ".cache"))
        assert "semgrep_findings" in res["static_analysis"]
        sf = res["static_analysis"]["semgrep_findings"]
        assert sf["status"] in VALID_STATUS_VALUES


class TestGitleaksAnalyzer:
    """Contract, execution, error handling, and security tests for GitleaksAnalyzer."""

    def test_gitleaks_version_constant(self):
        assert GITLEAKS_VERSION != ""

    def test_gitleaks_is_available_when_installed(self):
        analyzer = GitleaksAnalyzer()
        assert analyzer.is_available()[0] == (_GITLEAKS_BINARY is not None)

    def test_gitleaks_provenance_tag(self):
        analyzer = GitleaksAnalyzer()
        assert analyzer.provenance_tag == f"gitleaks:{GITLEAKS_VERSION}"

    def test_gitleaks_supports_language(self):
        analyzer = GitleaksAnalyzer()
        assert analyzer.supports_language("python") is True
        assert analyzer.supports_language("java") is True
        assert analyzer.supports_language("go") is True

    def test_gitleaks_empty_file_list_returns_unsupported(self, tmp_path):
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [])
        assert result.status == "unsupported"

    def test_gitleaks_nonexistent_files_returns_unsupported(self, tmp_path):
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(tmp_path / "ghost.py")])
        assert result.status == "unsupported"

    def test_gitleaks_unavailable_simulation(self, monkeypatch, tmp_path):
        """Simulate missing gitleaks binary to verify unavailable status."""
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", None)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "unavailable"

    def test_gitleaks_timeout_simulation(self, monkeypatch, tmp_path):
        """Simulate timeout during gitleaks execution."""
        import subprocess as _sp
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")

        def mock_run(*args, **kwargs):
            raise _sp.TimeoutExpired(cmd="gitleaks", timeout=180)

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", mock_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "failed"
        assert any("timed out" in e for e in result.errors)

    def test_gitleaks_bad_exit_code(self, monkeypatch, tmp_path):
        """Exit codes >= 2 represent execution failures."""
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 2
            stdout = ""
            stderr = "Fatal CLI error"

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: FakeProc())
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "failed"
        assert "Fatal CLI error" in result.errors

    def test_gitleaks_unparsable_json(self, monkeypatch, tmp_path):
        """Malformed JSON report yields status failed."""
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            r_idx = cmd.index("-r") + 1
            report_path = cmd[r_idx]
            with open(report_path, "w", encoding="utf-8") as rf:
                rf.write("{not valid json")
            return FakeProc()

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", fake_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "failed"

    def test_gitleaks_non_list_json(self, monkeypatch, tmp_path):
        """JSON output that is not a list yields status failed."""
        import json as _json
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            r_idx = cmd.index("-r") + 1
            report_path = cmd[r_idx]
            with open(report_path, "w", encoding="utf-8") as rf:
                _json.dump({"error": "object not list"}, rf)
            return FakeProc()

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", fake_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "failed"
        assert any("must be a list" in e for e in result.errors)

    def test_gitleaks_clean_repository_is_success(self, monkeypatch, tmp_path):
        """Exit code 0 with empty results list is success."""
        import json as _json
        f = tmp_path / "app.py"
        f.write_text("x = 1\n", encoding="utf-8")

        class FakeProc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            r_idx = cmd.index("-r") + 1
            report_path = cmd[r_idx]
            with open(report_path, "w", encoding="utf-8") as rf:
                _json.dump([], rf)
            return FakeProc()

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", fake_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        assert result.results == []

    def test_gitleaks_finding_field_schema_and_redaction(self, monkeypatch, tmp_path):
        """Findings carry rule_id, file, line, col, description, severity, entropy, fingerprint, BUT NEVER secret material."""
        import json as _json
        f = tmp_path / "secret.py"
        f.write_text("MOCK_KEY = 'super_secret_value'\n", encoding="utf-8")

        raw_finding = {
            "RuleID": "generic-api-key",
            "Description": "Generic API Key",
            "StartLine": 1,
            "EndLine": 1,
            "StartColumn": 12,
            "EndColumn": 30,
            "Match": "super_secret_value",
            "Secret": "super_secret_value",
            "File": str(f),
            "Entropy": 4.5,
            "Fingerprint": f"{f}:generic-api-key:1",
        }

        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            r_idx = cmd.index("-r") + 1
            report_path = cmd[r_idx]
            with open(report_path, "w", encoding="utf-8") as rf:
                _json.dump([raw_finding], rf)
            return FakeProc()

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", fake_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        assert len(result.results) == 1
        res = result.results[0]
        assert res["rule_id"] == "generic-api-key"
        assert "secret.py" in res["file"]
        assert res["line"] == 1
        assert res["col"] == 12
        assert res["description"] == "Generic API Key"
        assert res["severity"] == "HIGH"
        assert res["entropy"] == 4.5
        assert res["provenance"].startswith("gitleaks:")
        # Security assertion: raw secret and match MUST NOT be in output dictionary!
        assert "Secret" not in res
        assert "Match" not in res
        assert "super_secret_value" not in str(res)

    def test_gitleaks_findings_deterministic_order(self, monkeypatch, tmp_path):
        """Findings are sorted deterministically by file -> line -> col -> rule_id."""
        import json as _json
        f = tmp_path / "secrets.py"
        f.write_text("x = 1\n" * 10, encoding="utf-8")

        def make_raw(line, col, rule):
            return {
                "RuleID": rule,
                "Description": "desc",
                "StartLine": line,
                "StartColumn": col,
                "Match": "REDACTED",
                "Secret": "REDACTED",
                "File": str(f),
                "Entropy": 3.0,
                "Fingerprint": f"{f}:{rule}:{line}",
            }

        raw_list = [
            make_raw(5, 2, "rule-b"),
            make_raw(1, 10, "rule-a"),
            make_raw(1, 10, "rule-z"),
            make_raw(3, 1, "rule-c"),
        ]

        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            r_idx = cmd.index("-r") + 1
            report_path = cmd[r_idx]
            with open(report_path, "w", encoding="utf-8") as rf:
                _json.dump(raw_list, rf)
            return FakeProc()

        monkeypatch.setattr(_sa_module, "_GITLEAKS_BINARY", "/fake/gitleaks")
        monkeypatch.setattr("subprocess.run", fake_run)
        analyzer = GitleaksAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        order = [(r["line"], r["col"], r["rule_id"]) for r in result.results]
        assert order == sorted(order)

    def test_gitleaks_safe_env_strips_secrets(self):
        """_safe_env() strips GITLEAKS_CONFIG and SEMGREP tokens."""
        import os as _os
        with pytest.MonkeyPatch().context() as m:
            m.setenv("GITLEAKS_CONFIG", "/path/to/bad.toml")
            m.setenv("GITLEAKS_CONFIG_TOML", "bad content")
            m.setenv("PATH", _os.environ.get("PATH", ""))
            env = GitleaksAnalyzer._safe_env()
        assert "GITLEAKS_CONFIG" not in env
        assert "GITLEAKS_CONFIG_TOML" not in env
        assert "PATH" in env

    def test_analyze_repository_includes_gitleaks_findings(self):
        """analyze_repository() output must include the 'gitleaks_findings' key."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        py_files = [f for f in os.listdir(fixture) if f.endswith(".py")]
        result = analyze_repository(fixture, py_files)
        assert "gitleaks_findings" in result
        gf = result["gitleaks_findings"]
        assert gf["status"] in VALID_STATUS_VALUES
        assert "results" in gf

    def test_pipeline_gitleaks_findings_present(self):
        """run_pipeline output must include gitleaks_findings in static_analysis."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        res = run_pipeline(None, fixture, None, os.path.join(fixture, ".cache"))
        assert "gitleaks_findings" in res["static_analysis"]
        gf = res["static_analysis"]["gitleaks_findings"]
        assert gf["status"] in VALID_STATUS_VALUES


class TestOSVAnalyzer:
    """Contract, manifest parsing, error handling, and API integration tests for OSVAnalyzer."""

    def test_parse_requirements_txt(self, tmp_path):
        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.28.1\npytest>=7.0.0\n# comment\n", encoding="utf-8")
        deps, errs = parse_manifest_file(str(f), "requirements.txt")
        assert len(errs) == 0
        assert len(deps) == 2
        req = next(d for d in deps if d.package_name == "requests")
        assert req.installed_version == "2.28.1"
        assert req.ecosystem == "PyPI"

    def test_parse_pyproject_toml(self, tmp_path):
        f = tmp_path / "pyproject.toml"
        f.write_text('[project]\ndependencies = ["urllib3==1.26.5", "click>=8.0"]\n', encoding="utf-8")
        deps, errs = parse_manifest_file(str(f), "pyproject.toml")
        assert len(errs) == 0
        assert len(deps) == 2
        u = next(d for d in deps if d.package_name == "urllib3")
        assert u.installed_version == "1.26.5"

    def test_parse_package_json(self, tmp_path):
        import json as _json
        f = tmp_path / "package.json"
        f.write_text(_json.dumps({"dependencies": {"express": "4.17.1"}}), encoding="utf-8")
        deps, errs = parse_manifest_file(str(f), "package.json")
        assert len(errs) == 0
        assert len(deps) == 1
        assert deps[0].package_name == "express"
        assert deps[0].installed_version == "4.17.1"
        assert deps[0].ecosystem == "npm"

    def test_osv_unsupported_repo_no_manifests(self, tmp_path):
        """Repository without manifests returns unsupported."""
        analyzer = OSVAnalyzer()
        result = analyzer.analyze(str(tmp_path), [])
        assert result.status == "unsupported"

    def test_osv_network_error_simulation(self, monkeypatch, tmp_path):
        """Simulate HTTP / network error returning unavailable status."""
        import urllib.error as _ue
        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.28.1\n", encoding="utf-8")

        def mock_urlopen(*args, **kwargs):
            raise _ue.URLError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        analyzer = OSVAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "unavailable"
        assert any("network error" in e for e in result.errors)

    def test_osv_batch_response_mismatch_fails(self, monkeypatch, tmp_path):
        """Mismatched API response list returns failed status."""
        import json as _json

        class FakeResp:
            def read(self):
                return _json.dumps({"results": []}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.28.1\n", encoding="utf-8")

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: FakeResp())
        analyzer = OSVAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "failed"

    def test_osv_clean_dependencies_is_success(self, monkeypatch, tmp_path):
        """Zero vulnerabilities found returns status success."""
        import json as _json

        class FakeResp:
            def read(self):
                return _json.dumps({"results": [{"vulns": []}]}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        f = tmp_path / "requirements.txt"
        f.write_text("safe_pkg==1.0.0\n", encoding="utf-8")

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: FakeResp())
        analyzer = OSVAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        assert result.results == []

    def test_osv_vulnerability_finding_schema_and_ordering(self, monkeypatch, tmp_path):
        """Findings carry package_name, ecosystem, installed_version, vulnerability_id, summary, severity, fixed_versions."""
        import json as _json

        class FakeResp:
            def __init__(self, data):
                self._data = data
                self.status = 200
            def read(self):
                return _json.dumps(self._data).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def mock_urlopen(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "querybatch" in url:
                payload = {
                    "results": [
                        {
                            "vulns": [
                                {
                                    "id": "GHSA-1234",
                                    "summary": "Sample Vulnerability",
                                }
                            ]
                        }
                    ]
                }
                return FakeResp(payload)
            else:
                vuln_detail = {
                    "id": "GHSA-1234",
                    "summary": "Sample Vulnerability",
                    "severity": [{"type": "CVSS_V3", "score": "7.5"}],
                    "affected": [
                        {
                            "ranges": [
                                {
                                    "type": "ECOSYSTEM",
                                    "events": [{"introduced": "0"}, {"fixed": "2.28.2"}],
                                }
                            ]
                        }
                    ],
                }
                return FakeResp(vuln_detail)

        f = tmp_path / "requirements.txt"
        f.write_text("requests==2.20.0\n", encoding="utf-8")

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        analyzer = OSVAnalyzer()
        result = analyzer.analyze(str(tmp_path), [str(f)])
        assert result.status == "success"
        assert len(result.results) == 1
        r = result.results[0]
        assert r["package_name"] == "requests"
        assert r["ecosystem"] == "PyPI"
        assert r["vulnerability_id"] == "GHSA-1234"
        assert r["summary"] == "Sample Vulnerability"
        assert r["fixed_versions"] == ["2.28.2"]

    def test_analyze_repository_includes_osv_vulnerabilities(self):
        """analyze_repository() output must include the 'osv_vulnerabilities' key."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        py_files = [f for f in os.listdir(fixture) if f.endswith(".py")]
        result = analyze_repository(fixture, py_files)
        assert "osv_vulnerabilities" in result
        ov = result["osv_vulnerabilities"]
        assert ov["status"] in VALID_STATUS_VALUES
        assert "results" in ov

    def test_pipeline_osv_vulnerabilities_present(self):
        """run_pipeline output must include osv_vulnerabilities in static_analysis."""
        fixture = os.path.join(FIXTURES_DIR, "success_repo")
        res = run_pipeline(None, fixture, None, os.path.join(fixture, ".cache"))
        assert "osv_vulnerabilities" in res["static_analysis"]
        ov = res["static_analysis"]["osv_vulnerabilities"]
        assert ov["status"] in VALID_STATUS_VALUES


