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

Tools wired up in this Tier-1 (Python-only) MVP: radon, bandit, lizard.
Deliberately NOT wired up yet (documented, not silently skipped):
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
from typing import List, Optional

import radon
import radon.complexity as radon_cc
from radon.visitors import ComplexityVisitor
from radon.metrics import mi_visit

from util import is_test_file
from analyzer_contract import BaseAnalyzer, AnalyzerResult, AnalyzerStatus


def _safe_version(pkg_name: str) -> str:
    try:
        return pkg_version(pkg_name)
    except PackageNotFoundError:
        return "unknown"


RADON_VERSION = getattr(radon, "__version__", _safe_version("radon"))
BANDIT_VERSION = _safe_version("bandit")

# Lizard version: lizard exposes `lizard.version` (a plain string), not __version__.
try:
    import lizard as _lizard_mod
    LIZARD_VERSION = str(getattr(_lizard_mod, "version", _safe_version("lizard")))
except ImportError:
    _lizard_mod = None  # type: ignore[assignment]
    LIZARD_VERSION = "unavailable"


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
      "success"     -> scan completed cleanly
      "unavailable" -> bandit executable not installed in environment
      "failed"      -> bandit crashed, timed out, unexpected exit code
    """
    if not prod_files_rel:
        return "success", []  # nothing to scan is a legitimate success

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
        print("[static_analysis] bandit executable not found -- security status = unavailable", file=sys.stderr)
        return "unavailable", []
    except Exception as exc:
        print(f"[static_analysis] bandit execution error: {exc} -- security status = failed", file=sys.stderr)
        return "failed", []

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


# ---------------------------------------------------------------------------
# Session 3 — LizardAnalyzer (BaseAnalyzer contract)
# ---------------------------------------------------------------------------

@dataclass
class LizardFunctionResult:
    """Per-function result from Lizard (language-agnostic)."""
    file: str
    function: str
    line: int
    cyclomatic_complexity: int
    nloc: int
    token_count: int
    max_nesting_depth: int
    provenance: str = f"lizard:{LIZARD_VERSION}"


class LizardAnalyzer(BaseAnalyzer):
    """
    Language-agnostic cyclomatic-complexity analyzer backed by the `lizard`
    package (pip-installable, pure Python, supports 30+ languages).

    Contract:
      - unavailable  : `lizard` package not importable
      - unsupported  : called with an empty file list
      - success      : all files analyzed cleanly
      - partial      : at least one file failed but at least one succeeded
      - failed       : every file failed (or single-file crash with no results)
    """

    # Languages whose source files Lizard can meaningfully analyze.
    # This list is intentionally conservative -- Lizard supports more,
    # but we only claim support for languages the pipeline currently handles.
    SUPPORTED_LANGUAGES = {
        "python", "java", "javascript", "typescript", "c", "c++", "c#",
        "go", "ruby", "swift", "kotlin", "rust", "scala",
    }

    def __init__(self) -> None:
        super().__init__(name="lizard", version=LIZARD_VERSION)

    # --- BaseAnalyzer interface ---

    def is_available(self) -> tuple[bool, Optional[str]]:
        if _lizard_mod is None:
            return False, "Package 'lizard' is not installed in this environment (pip install lizard>=1.17)"
        return True, None

    def supports_language(self, language: str) -> bool:
        return language.lower() in self.SUPPORTED_LANGUAGES

    def analyze(self, repo_root: str, files: List[str]) -> AnalyzerResult:
        """Run Lizard over *files* (absolute or relative to *repo_root*)."""
        avail, err = self.is_available()
        if not avail:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=[err] if err else [],
                provenance=self.provenance_tag,
                metadata={"lizard_version": LIZARD_VERSION},
            )

        if not files:
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "No files provided for analysis"},
            )

        results: List[LizardFunctionResult] = []
        errors: List[str] = []
        file_success_count = 0

        for f in sorted(files):  # deterministic ordering
            abs_path = f if os.path.isabs(f) else os.path.join(repo_root, f)
            rel_path = os.path.relpath(abs_path, repo_root).replace("\\", "/")
            try:
                file_info = _lizard_mod.analyze_file(abs_path)
                if file_info is None:
                    errors.append(f"{rel_path}: lizard returned no result")
                    continue
                for fn in file_info.function_list:
                    results.append(LizardFunctionResult(
                        file=rel_path,
                        function=fn.name,
                        line=fn.start_line,
                        cyclomatic_complexity=fn.cyclomatic_complexity,
                        nloc=fn.nloc,
                        token_count=fn.token_count,
                        max_nesting_depth=fn.max_nesting_depth,
                    ))
                file_success_count += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{rel_path}: {exc}")

        if file_success_count == 0 and errors:
            status = AnalyzerStatus.FAILED
        elif errors:
            status = AnalyzerStatus.PARTIAL
        else:
            status = AnalyzerStatus.SUCCESS

        return AnalyzerResult(
            status=status,
            results=[asdict(r) for r in results],
            errors=errors,
            provenance=self.provenance_tag,
            metadata={
                "lizard_version": LIZARD_VERSION,
                "files_analyzed": file_success_count,
                "files_failed": len(errors),
            },
        )


# Module-level singleton — created once, reused across calls.
_LIZARD_ANALYZER = LizardAnalyzer()


def analyze_repository(repo_root: str, py_files_rel: list) -> dict:
    """
    py_files_rel: ALL python files found (test + production). This function
    partitions them itself using the single shared is_test_file() definition
    so complexity/maintainability/security all see the identical split.

    Lizard complexity runs over production files and is language-agnostic;
    it supplements (not replaces) the Radon per-file complexity already
    captured for Python.
    """
    if not py_files_rel:
        return {
            "scope_policy": "production_code_only",
            "production_files_analyzed": 0,
            "test_files_excluded": 0,
            "complexity": {"status": "unsupported", "results": []},
            "maintainability": {"status": "unsupported", "results": []},
            "security": {"status": "unsupported", "results": []},
            "lizard_complexity": {"status": "unsupported", "results": []},
        }

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

    # --- Lizard (language-agnostic cyclomatic complexity) ---
    # Converts relative paths to absolute before passing to LizardAnalyzer.
    abs_prod_files = [os.path.join(repo_root, f) for f in prod_files]
    lizard_result = _LIZARD_ANALYZER.analyze(repo_root, abs_prod_files)
    lizard_dict = lizard_result.to_dict()

    return {
        "scope_policy": "production_code_only",
        "production_files_analyzed": len(prod_files),
        "test_files_excluded": len(test_files),
        "complexity": {"status": complexity_status, "results": [asdict(c) for c in complexity_results]},
        "maintainability": {"status": maintainability_status, "results": [asdict(m) for m in maintainability_results]},
        "security": {"status": security_status, "results": [asdict(s) for s in security_results]},
        "lizard_complexity": lizard_dict,
    }
