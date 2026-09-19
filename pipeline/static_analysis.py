"""
Wraps third-party deterministic tools and normalizes their output into a
single schema. Every metric is tagged with the exact tool name AND version
that produced it (now actually captured, not just claimed).

Every stage reports a status of "success" | "partial" | "failed" so that a
tool crash/timeout can never silently masquerade as "no issues found" --
that was a real correctness bug in the previous version (bandit failure ->
empty list -> security sub-score of 100, i.e. a broken analysis looking
like a spotless repository).

Test-file policy: this module decides production-vs-test split using ONE
shared definition (util.is_test_file), then applies it identically to
complexity, maintainability, AND security -- one shared definition, applied
identically everywhere, so the three metrics can no longer drift out of
sync the way they did before (tests were excluded from bandit but not from
radon in the previous version).

Tools wired up in this Tier-1 (Python-only) MVP: radon, bandit.
Deliberately NOT wired up yet (documented, not silently skipped):
  - lizard    : next after this fix pass, per review feedback
  - semgrep   : heavy, rule-config-dependent; add once Tier 1 core is stable
  - gitleaks  : Go binary, not pip-installable; needs a separate container step
  - OSV.dev   : requires outbound network call; wire in the deployed environment
"""
from __future__ import annotations
import subprocess
import json
import os
import sys
from dataclasses import dataclass, asdict
from importlib.metadata import version as pkg_version, PackageNotFoundError

import radon
import radon.complexity as radon_cc
from radon.visitors import ComplexityVisitor
from radon.metrics import mi_visit

from util import is_test_file


def _safe_version(pkg_name: str) -> str:
    try:
        return pkg_version(pkg_name)
    except PackageNotFoundError:
        return "unknown"


RADON_VERSION = getattr(radon, "__version__", _safe_version("radon"))
BANDIT_VERSION = _safe_version("bandit")


@dataclass
class ComplexityResult:
    file: str
    function: str
    line: int
    cyclomatic_complexity: int
    rank: str
    provenance: str = f"radon:{RADON_VERSION}:cc_visit"


@dataclass
class MaintainabilityResult:
    file: str
    maintainability_index: float
    provenance: str = f"radon:{RADON_VERSION}:mi_visit"


@dataclass
class SecurityIssue:
    file: str
    line: int
    issue_text: str
    severity: str
    confidence: str
    test_id: str
    provenance: str = f"bandit:{BANDIT_VERSION}"


def run_radon_complexity(filepath: str, rel_path: str):
    """Returns (status, results). status is 'success' or 'failed' for this one file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return "failed", []
    try:
        blocks = ComplexityVisitor.from_code(source).functions
    except SyntaxError:
        return "failed", []
    results = [
        ComplexityResult(file=rel_path, function=b.name, line=b.lineno,
                          cyclomatic_complexity=b.complexity, rank=radon_cc.cc_rank(b.complexity))
        for b in blocks
    ]
    return "success", results


def run_radon_maintainability(filepath: str, rel_path: str):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
    except OSError:
        return "failed", None
    try:
        mi = mi_visit(source, multi=True)
    except Exception:
        return "failed", None
    return "success", MaintainabilityResult(file=rel_path, maintainability_index=round(mi, 2))


def run_bandit(repo_root: str, prod_files_rel: list):
    """
    Runs bandit only over production (non-test) files, using the same
    is_test_file() definition as the complexity/maintainability stages.

    Returns (status, issues) where status is:
      "success" -> bandit ran (exit code 0 or 1, its documented "scan
                   completed" contract -- 1 means issues were found, 0
                   means none were, neither is a crash) and returned
                   parseable JSON with a results list
      "failed"  -> bandit crashed, timed out, exited with any code other
                   than 0/1 (previously NOT checked at all -- an unexpected
                   exit code fell through to parsing whatever stdout
                   happened to contain, which could silently look like a
                   clean scan), or returned unparsable/malformed output
                   (issues will be [] in this case -- callers MUST check
                   status before treating [] as "no issues found")
    """
    if not prod_files_rel:
        return "success", []  # nothing to scan is a legitimate, honest success

    abs_targets = [os.path.join(repo_root, f) for f in prod_files_rel]
    try:
        proc = subprocess.run(
            ["bandit", "-f", "json", "-q", *abs_targets],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("[static_analysis] bandit TIMED OUT -- security status = failed", file=sys.stderr)
        return "failed", []
    except FileNotFoundError:
        print("[static_analysis] bandit executable not found -- security status = failed", file=sys.stderr)
        return "failed", []
    except Exception as exc:
        print(f"[static_analysis] bandit execution error: {exc} -- security status = failed", file=sys.stderr)
        return "failed", []

    # bandit's own contract: 0 = ran clean, 1 = ran and found issues.
    # Anything else (2 = usage/internal error, or a signal-killed negative
    # code) means the scan itself did not complete trustworthily and must
    # never be parsed as if it did.
    if proc.returncode not in (0, 1):
        print(f"[static_analysis] bandit exited with unexpected code {proc.returncode} "
              f"-- security status = failed. stderr: {proc.stderr.strip()[:500]}", file=sys.stderr)
        return "failed", []

    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {"results": []}
    except json.JSONDecodeError:
        print("[static_analysis] bandit returned unparsable output -- security status = failed", file=sys.stderr)
        return "failed", []

    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        print("[static_analysis] bandit JSON did not contain a valid results list "
              "-- security status = failed", file=sys.stderr)
        return "failed", []

    issues = [
        SecurityIssue(
            file=os.path.relpath(r["filename"], repo_root),
            line=r["line_number"], issue_text=r["issue_text"],
            severity=r["issue_severity"], confidence=r["issue_confidence"],
            test_id=r["test_id"],
        )
        for r in raw_results
    ]
    return "success", issues


def analyze_repository(repo_root: str, py_files_rel: list) -> dict:
    """
    py_files_rel: ALL python files found (test + production). This function
    partitions them itself using the single shared is_test_file() definition
    so complexity/maintainability/security all see the identical split.
    """
    prod_files = [f for f in py_files_rel if not is_test_file(f)]
    test_files = [f for f in py_files_rel if is_test_file(f)]

    complexity_results, maintainability_results = [], []
    any_complexity_failure = any_maintainability_failure = False

    for rel in prod_files:
        abs_path = os.path.join(repo_root, rel)
        status, results = run_radon_complexity(abs_path, rel)
        if status == "failed":
            any_complexity_failure = True
        complexity_results.extend(results)

        status, mi = run_radon_maintainability(abs_path, rel)
        if status == "failed":
            any_maintainability_failure = True
        elif mi:
            maintainability_results.append(mi)

    complexity_status = "success"
    if any_complexity_failure:
        complexity_status = "partial" if complexity_results else "failed"
    maintainability_status = "success"
    if any_maintainability_failure:
        maintainability_status = "partial" if maintainability_results else "failed"

    security_status, security_results = run_bandit(repo_root, prod_files)

    return {
        "scope_policy": "production_code_only",
        "production_files_analyzed": len(prod_files),
        "test_files_excluded": len(test_files),
        "complexity": {"status": complexity_status, "results": [asdict(c) for c in complexity_results]},
        "maintainability": {"status": maintainability_status, "results": [asdict(m) for m in maintainability_results]},
        "security": {"status": security_status, "results": [asdict(s) for s in security_results]},
    }
