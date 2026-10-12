"""
Hermetic Semgrep tests: the default suite must never need network access.

* Default suite  -> pinned local rules (tests/semgrep_rules/test-rules.yml).
* Live `--config auto` -> opt-in, marked `network`, excluded by default.
A skipped/excluded live scan is NOT evidence that security checks passed.
"""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import static_analysis
from static_analysis import SemgrepAnalyzer, resolve_semgrep_config

RULES = str(ROOT / "tests" / "semgrep_rules" / "test-rules.yml")
VULN_REPO = str(ROOT / "tests" / "fixtures" / "semgrep_vuln_repo")


def _need_semgrep():
    assert shutil.which("semgrep"), (
        "semgrep must be installed (pip install -r requirements.txt) for the "
        "hermetic Semgrep tests; refusing to skip silently"
    )


def test_default_suite_uses_pinned_local_rules_not_auto():
    # conftest sets this for every non-network test
    assert os.environ.get("SEMGREP_CONFIG") == RULES


def test_semgrep_finds_known_issues_offline_and_fast(monkeypatch):
    _need_semgrep()
    monkeypatch.setenv("SEMGREP_CONFIG", RULES)
    start = time.monotonic()
    res = SemgrepAnalyzer().analyze(VULN_REPO, [os.path.join(VULN_REPO, "app.py")])
    elapsed = time.monotonic() - start
    assert res.status == "success", res.errors
    sev = sorted(r["severity"] for r in res.results)
    assert sev == ["ERROR", "INFO", "WARNING"]
    assert {r["rule_id"].split(".")[-1] for r in res.results} == {
        "eval-use", "subprocess-shell-true", "assert-in-code"}
    assert elapsed < 60, f"offline scan took {elapsed:.1f}s; something is hitting the network"


def test_pipeline_fixture_runs_hermetically(tmp_path):
    _need_semgrep()
    from main import run_pipeline
    res = run_pipeline(None, os.path.join(str(ROOT / "tests" / "fixtures"), "success_repo"),
                       None, str(tmp_path))
    assert res["static_analysis"]["semgrep_findings"]["status"] in ("success", "partial")


@pytest.mark.parametrize("bad", [
    "p/ci", "r/python", "https://semgrep.dev/c/p/default", "relative/rules.yml",
    "/does/not/exist.yml", VULN_REPO,  # directory without rules is fine only if it exists; see below
])
def test_unsafe_or_missing_config_is_rejected(monkeypatch, bad):
    monkeypatch.setenv("SEMGREP_CONFIG", bad)
    cfg, err = resolve_semgrep_config(repo_root="/tmp/some-repo")
    if bad == VULN_REPO:
        # an existing absolute directory outside the scanned repo is allowed
        assert err is None and cfg == bad
    else:
        assert cfg is None and err


def test_config_inside_scanned_repo_is_rejected(monkeypatch):
    # a repo must never be able to supply its own rules
    inside = os.path.join(VULN_REPO, "app.py")
    monkeypatch.setenv("SEMGREP_CONFIG", inside)
    cfg, err = resolve_semgrep_config(repo_root=VULN_REPO)
    assert cfg is None and "inside the scanned repository" in err


def test_rejected_config_fails_analysis_without_running_semgrep(monkeypatch):
    monkeypatch.setenv("SEMGREP_CONFIG", "p/ci")

    def boom(*a, **k):
        raise AssertionError("semgrep must not be executed with an unsafe config")
    monkeypatch.setattr(static_analysis.subprocess, "run", boom)
    res = SemgrepAnalyzer().analyze(VULN_REPO, [os.path.join(VULN_REPO, "app.py")])
    assert res.status == "failed" and any("SEMGREP_CONFIG" in e for e in res.errors)


def test_unset_config_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("SEMGREP_CONFIG", raising=False)
    assert resolve_semgrep_config(repo_root="/tmp/x") == ("auto", None)
    monkeypatch.setenv("SEMGREP_CONFIG", "auto")
    assert resolve_semgrep_config(repo_root="/tmp/x") == ("auto", None)


def test_local_config_adds_offline_flags(monkeypatch):
    _need_semgrep()
    monkeypatch.setenv("SEMGREP_CONFIG", RULES)
    seen = {}

    class P:
        returncode, stdout, stderr = 0, '{"results": [], "errors": []}', ""

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return P()
    monkeypatch.setattr(static_analysis.subprocess, "run", fake_run)
    SemgrepAnalyzer().analyze(VULN_REPO, [os.path.join(VULN_REPO, "app.py")])
    cmd = seen["cmd"]
    assert cmd[cmd.index("--config") + 1] == RULES
    assert "--metrics=off" in cmd and "--disable-version-check" in cmd


@pytest.mark.network
def test_live_auto_config_scan(monkeypatch):
    """Opt-in: run with `pytest -m network`. Needs outbound access to semgrep.dev."""
    _need_semgrep()
    monkeypatch.delenv("SEMGREP_CONFIG", raising=False)
    res = SemgrepAnalyzer().analyze(VULN_REPO, [os.path.join(VULN_REPO, "app.py")])
    assert res.status in ("success", "partial"), res.errors
