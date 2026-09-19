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

Tools wired up in this Tier-1 (Python-only) MVP: radon, bandit, lizard, semgrep.
Deliberately NOT wired up yet (documented, not silently skipped):
  - gitleaks  : Go binary, not pip-installable; needs a separate container step
  - OSV.dev   : requires outbound network call; wire in the deployed environment
"""
from __future__ import annotations
import shutil
import subprocess
import json
import os
import sys
import tempfile
import re
import urllib.request
import urllib.error
import concurrent.futures
try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore[assignment]
from dataclasses import dataclass, asdict, field
from importlib.metadata import version as pkg_version, PackageNotFoundError
from typing import Any, Dict, List, Optional

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

# Module-level singletons — created once, reused across calls.
_LIZARD_ANALYZER = LizardAnalyzer()


# ---------------------------------------------------------------------------
# Session 4 — SemgrepAnalyzer (BaseAnalyzer contract)
# ---------------------------------------------------------------------------

# Detect Semgrep version once at import time.  Semgrep must be a binary on
# PATH (pip-installed or standalone binary); we capture its version by
# running `semgrep --version` so the provenance tag is always accurate.

def _detect_semgrep() -> tuple[str | None, str]:
    """
    Returns (semgrep_path, version_string) if the semgrep binary is on PATH,
    or (None, 'unavailable') if not.

    Uses shutil.which() for detection (cheap, no subprocess) and then runs
    `semgrep --version` once for the canonical version string.
    """
    binary = shutil.which("semgrep")
    if binary is None:
        return None, "unavailable"
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ},  # pass env through but do not add extras
        )
        version_line = (proc.stdout or proc.stderr or "").strip().splitlines()
        version_str = version_line[0] if version_line else "unknown"
        # Semgrep prints e.g. "1.87.0" or "semgrep 1.87.0" depending on version
        version_str = version_str.removeprefix("semgrep ").strip()
        return binary, version_str
    except Exception:  # noqa: BLE001
        return binary, "unknown"


_SEMGREP_BINARY, SEMGREP_VERSION = _detect_semgrep()


@dataclass
class SemgrepFinding:
    """Normalized single Semgrep finding."""
    rule_id: str
    file: str
    line: int
    col: int
    message: str
    severity: str
    cwe: List[str] = field(default_factory=list)
    provenance: str = ""

    def __post_init__(self):
        if not self.provenance:
            self.provenance = f"semgrep:{SEMGREP_VERSION}"


class SemgrepAnalyzer(BaseAnalyzer):
    """
    SAST/pattern-based security analyzer backed by the Semgrep binary.

    Security model
    --------------
    * Repository contents are treated as UNTRUSTED INPUT.
    * We NEVER execute repository code (Semgrep is a pattern matcher only).
    * We pass --config auto (Semgrep-managed OSS ruleset) -- no custom rules
      from the target repo are loaded, preventing rule-injection attacks.
    * We pass --no-git-ignore so analysis is not silently narrowed by a
      repo-provided .semgrepignore; we control the file list ourselves.
    * We pass --config auto (Semgrep-managed OSS ruleset). Note that --metrics=off
      is NOT passed because Semgrep auto-config requires metrics to be enabled/default.
    * We do not pass any repository-provided environment variables.
    * We cap the subprocess timeout at 180 s to prevent DoS.

    Contract
    --------
      - unavailable  : semgrep binary not on PATH
      - unsupported  : no files provided
      - success      : scan completed; findings list may be empty
      - failed       : unexpected exit code, timeout, or unparsable output
      - partial      : (not currently raised -- Semgrep fails atomically)
    """

    # Languages Semgrep can analyze that are within our pipeline scope.
    SUPPORTED_LANGUAGES = {
        "python", "java", "javascript", "typescript", "go", "ruby",
        "c", "c++", "c#", "rust", "scala", "kotlin",
    }

    # Semgrep exit codes: 0 = success/no findings, 1 = success + findings,
    # 2 = error.  We treat 0 and 1 as valid; everything else as failed.
    VALID_EXIT_CODES = {0, 1}

    # Subprocess timeout (seconds).  Keeps a slow/large repo from blocking.
    TIMEOUT_SECONDS = 180

    def __init__(self) -> None:
        super().__init__(name="semgrep", version=SEMGREP_VERSION)

    # --- BaseAnalyzer interface ---

    def is_available(self) -> tuple[bool, Optional[str]]:
        if _SEMGREP_BINARY is None:
            return False, (
                "'semgrep' binary not found on PATH. "
                "Install via: pip install semgrep  (or use the standalone binary)."
            )
        return True, None

    def supports_language(self, language: str) -> bool:
        return language.lower() in self.SUPPORTED_LANGUAGES

    def analyze(self, repo_root: str, files: List[str]) -> AnalyzerResult:
        """
        Run Semgrep over *files* (absolute paths expected).

        We pass individual file paths rather than the repo root so Semgrep
        only scans the files the pipeline decided are relevant (production,
        non-test Python).
        """
        avail, err = self.is_available()
        if not avail:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=[err] if err else [],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )

        if not files:
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "No files provided for analysis"},
            )

        # Resolve + deduplicate file paths; skip non-existent files silently
        # (they can't be untrusted input to the subprocess).
        abs_files = sorted({
            (f if os.path.isabs(f) else os.path.join(repo_root, f))
            for f in files
            if os.path.isfile(f if os.path.isabs(f) else os.path.join(repo_root, f))
        })
        if not abs_files:
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "None of the provided file paths exist on disk"},
            )

        cmd = [
            _SEMGREP_BINARY,
            "scan",
            "--json",              # machine-readable output
            "--no-git-ignore",    # don't let the repo narrow our scope
            "--config", "auto",   # Semgrep-managed OSS ruleset; NOT repo-provided
            "--quiet",            # suppress progress/banner noise on stdout
            *abs_files,           # explicit file list, not the whole repo root
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                cwd=repo_root,
                # Pass only a safe subset of environment variables.
                # Exclude: SEMGREP_APP_TOKEN, SEMGREP_LOGIN_TOKEN, CI secrets.
                env=self._safe_env(),
            )
        except subprocess.TimeoutExpired:
            print(
                f"[static_analysis] semgrep TIMED OUT after {self.TIMEOUT_SECONDS}s "
                "-- semgrep status = failed", file=sys.stderr
            )
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                errors=[f"semgrep timed out after {self.TIMEOUT_SECONDS}s"],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )
        except FileNotFoundError:
            # Binary disappeared after is_available() returned True (race condition)
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=["semgrep binary not found at execution time"],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )
        except Exception as exc:  # noqa: BLE001
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                errors=[f"semgrep execution error: {exc}"],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )

        if proc.returncode not in self.VALID_EXIT_CODES:
            stderr_snippet = (proc.stderr or "").strip()[:500]
            print(
                f"[static_analysis] semgrep exited with unexpected code "
                f"{proc.returncode} -- status = failed. stderr: {stderr_snippet}",
                file=sys.stderr,
            )
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                errors=[
                    f"semgrep exited {proc.returncode}",
                    *(([stderr_snippet]) if stderr_snippet else []),
                ],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION, "exit_code": proc.returncode},
            )

        # Parse JSON output defensively
        stdout = (proc.stdout or "").strip()
        if not stdout:
            # No stdout but valid exit code: treat as no findings
            return AnalyzerResult(
                status=AnalyzerStatus.SUCCESS,
                results=[],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION, "findings": 0},
            )

        try:
            data: Dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError as exc:
            print(
                f"[static_analysis] semgrep returned unparsable JSON -- status = failed: {exc}",
                file=sys.stderr,
            )
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                errors=[f"semgrep output not valid JSON: {exc}"],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                errors=["semgrep JSON did not contain a valid 'results' list"],
                provenance=self.provenance_tag,
                metadata={"semgrep_version": SEMGREP_VERSION},
            )

        # Capture any scan-level errors Semgrep itself reported
        scan_errors: List[str] = [
            str(e) for e in data.get("errors", []) if e
        ]

        findings: List[SemgrepFinding] = []
        parse_errors: List[str] = []

        for r in raw_results:
            try:
                extra = r.get("extra", {})
                metadata_block = extra.get("metadata", {})
                cwe_raw = metadata_block.get("cwe", [])
                if isinstance(cwe_raw, str):
                    cwe_raw = [cwe_raw]

                abs_path = r.get("path", "")
                rel_path = os.path.relpath(abs_path, repo_root).replace("\\", "/")

                findings.append(SemgrepFinding(
                    rule_id=r.get("check_id", "unknown"),
                    file=rel_path,
                    line=r.get("start", {}).get("line", 0),
                    col=r.get("start", {}).get("col", 0),
                    message=(extra.get("message") or "").strip(),
                    severity=(extra.get("severity") or "INFO").upper(),
                    cwe=[str(c) for c in cwe_raw if c],
                ))
            except Exception as exc:  # noqa: BLE001
                parse_errors.append(f"Failed to parse finding: {exc!r}")

        # Sort deterministically: file -> line -> col -> rule_id
        findings.sort(key=lambda f: (f.file, f.line, f.col, f.rule_id))

        all_errors = scan_errors + parse_errors
        status = AnalyzerStatus.SUCCESS
        if parse_errors and not findings:
            status = AnalyzerStatus.FAILED
        elif parse_errors:
            status = AnalyzerStatus.PARTIAL

        return AnalyzerResult(
            status=status,
            results=[asdict(f) for f in findings],
            errors=all_errors if all_errors else [],
            provenance=self.provenance_tag,
            metadata={
                "semgrep_version": SEMGREP_VERSION,
                "findings": len(findings),
                "scan_errors": len(scan_errors),
            },
        )

    @staticmethod
    def _safe_env() -> Dict[str, str]:
        """
        Returns a filtered copy of os.environ that strips secret tokens so
        they cannot be echoed into analysis output or logs.

        Excluded keys (case-insensitive prefixes):
          SEMGREP_APP_TOKEN, SEMGREP_LOGIN_TOKEN, CI secret patterns.
        """
        _SECRET_PREFIXES = (
            "SEMGREP_APP_TOKEN",
            "SEMGREP_LOGIN_TOKEN",
            "SEMGREP_API_TOKEN",
        )
        return {
            k: v for k, v in os.environ.items()
            if not any(k.upper().startswith(p) for p in _SECRET_PREFIXES)
        }


# Module-level singleton for SemgrepAnalyzer.
_SEMGREP_ANALYZER = SemgrepAnalyzer()


def _detect_gitleaks() -> tuple[Optional[str], str]:
    binary = shutil.which("gitleaks")
    if not binary:
        return None, "unavailable"
    try:
        proc = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            ver = proc.stdout.strip()
            if ver.lower().startswith("gitleaks version "):
                ver = ver[len("gitleaks version "):].strip()
            elif ver.lower().startswith("v"):
                ver = ver[1:].strip()
            return binary, ver
        return binary, "unknown"
    except Exception:
        return binary, "unknown"


_GITLEAKS_BINARY, GITLEAKS_VERSION = _detect_gitleaks()


@dataclass
class GitleaksFinding:
    """
    Normalized single Gitleaks secret detection finding.

    SECURITY MANDATE: Raw secret material ('Secret' or 'Match' strings from
    Gitleaks) MUST NEVER be stored, serialized, or exposed in output. Only
    metadata, location, rule IDs, descriptions, entropy, and fingerprints
    are captured.
    """
    rule_id: str
    file: str
    line: int
    col: int
    description: str
    severity: str = "HIGH"
    entropy: float = 0.0
    fingerprint: str = ""
    provenance: str = ""

    def __post_init__(self):
        if not self.provenance:
            self.provenance = f"gitleaks:{GITLEAKS_VERSION}"


class GitleaksAnalyzer(BaseAnalyzer):
    """
    Secret-detection analyzer backed by the Gitleaks binary.

    Security model
    --------------
    * Repository contents are treated as UNTRUSTED INPUT.
    * We NEVER execute repository code (Gitleaks is a regex/entropy scanner).
    * We pass --no-git so scanning acts directly on snapshot files deterministically.
    * We pass --redact so Gitleaks stdout/reports mask secrets.
    * We explicitly OMIT raw secret strings ('Secret'/'Match') from our output data model.
    * We pass -i non_existent_file to prevent repo-provided .gitleaksignore from ignoring leaks.
    * We pass env sanitized via _safe_env() to prevent GITLEAKS_CONFIG env injection.
    * We cap subprocess timeout at 180s to prevent DoS.

    Contract
    --------
      - unavailable  : gitleaks binary not on PATH
      - unsupported  : empty/non-existent file list
      - success      : scan completed cleanly (0 leaks OR 1+ leaks detected)
      - partial      : scan completed with individual item parsing errors
      - failed       : exit code 2+, malformed JSON output, timeout
    """

    TIMEOUT_SECONDS: int = 180

    def __init__(self) -> None:
        super().__init__(name="gitleaks", version=GITLEAKS_VERSION)

    def is_available(self) -> tuple[bool, Optional[str]]:
        if _GITLEAKS_BINARY is None:
            return False, "'gitleaks' binary not found on PATH."
        return True, None

    def supports_language(self, language: str) -> bool:
        return True

    def analyze(self, repo_root: str, files: List[str]) -> AnalyzerResult:
        abs_files = sorted({
            (f if os.path.isabs(f) else os.path.join(repo_root, f))
            for f in files
            if os.path.isfile(f if os.path.isabs(f) else os.path.join(repo_root, f))
        })
        if not abs_files:
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "None of the provided file paths exist on disk"},
            )

        avail, err = self.is_available()
        if not avail:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=[err] if err else [],
                provenance=self.provenance_tag,
                metadata={"reason": err or "gitleaks executable not found on PATH"},
            )

        temp_fd, temp_report_path = tempfile.mkstemp(suffix=".json", prefix="gitleaks_report_")
        os.close(temp_fd)

        cmd = [
            _GITLEAKS_BINARY,
            "detect",
            "--no-git",
            "--source", repo_root,
            "-f", "json",
            "-r", temp_report_path,
            "--redact",
            "--no-banner",
            "-i", os.path.join(repo_root, ".non_existent_gitleaks_ignore"),
            "--log-level", "error",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                cwd=repo_root,
                env=self._safe_env(),
            )
        except subprocess.TimeoutExpired:
            if os.path.exists(temp_report_path):
                os.remove(temp_report_path)
            print(
                f"[static_analysis] gitleaks TIMED OUT after {self.TIMEOUT_SECONDS}s",
                file=sys.stderr,
            )
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[f"gitleaks execution timed out after {self.TIMEOUT_SECONDS}s"],
            )
        except Exception as exc:
            if os.path.exists(temp_report_path):
                os.remove(temp_report_path)
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[f"Subprocess invocation error: {exc!r}"],
            )

        # Gitleaks exit codes: 0 = no leaks, 1 = leaks found.
        # Both represent successful scan execution. Exit codes >= 2 indicate errors.
        if proc.returncode not in (0, 1):
            if os.path.exists(temp_report_path):
                os.remove(temp_report_path)
            print(
                f"[static_analysis] gitleaks exited with unexpected code {proc.returncode}",
                file=sys.stderr,
            )
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[proc.stderr.strip() or f"Unexpected exit code {proc.returncode}"],
            )

        raw_json = ""
        scan_errors: List[str] = []
        if proc.stderr and proc.stderr.strip():
            scan_errors.append(proc.stderr.strip())

        try:
            if os.path.exists(temp_report_path):
                with open(temp_report_path, "r", encoding="utf-8") as f:
                    raw_json = f.read().strip()
                os.remove(temp_report_path)
            else:
                return AnalyzerResult(
                    status=AnalyzerStatus.FAILED,
                    provenance=self.provenance_tag,
                    errors=["Gitleaks did not produce a report file"],
                )
        except Exception as exc:
            if os.path.exists(temp_report_path):
                os.remove(temp_report_path)
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[f"Failed to read report file: {exc!r}"],
            )

        if not raw_json:
            raw_results = []
        else:
            try:
                raw_results = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                return AnalyzerResult(
                    status=AnalyzerStatus.FAILED,
                    provenance=self.provenance_tag,
                    errors=[f"Unparsable JSON from gitleaks: {exc!r}"],
                )

        if not isinstance(raw_results, list):
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=["gitleaks JSON root output must be a list"],
            )

        # Filter findings to only those matching our target files
        target_abs_norm = {os.path.abspath(target) for target in abs_files}
        findings: List[GitleaksFinding] = []
        parse_errors: List[str] = []

        for r in raw_results:
            try:
                if not isinstance(r, dict):
                    parse_errors.append(f"Invalid finding object: {r!r}")
                    continue
                file_path = r.get("File", "")
                abs_f = file_path if os.path.isabs(file_path) else os.path.join(repo_root, file_path)
                abs_f_norm = os.path.abspath(abs_f)

                if abs_f_norm in target_abs_norm:
                    rel_path = os.path.relpath(abs_f_norm, repo_root).replace("\\", "/")
                    findings.append(GitleaksFinding(
                        rule_id=str(r.get("RuleID", "unknown")),
                        file=rel_path,
                        line=int(r.get("StartLine", 0)),
                        col=int(r.get("StartColumn", 0)),
                        description=str(r.get("Description", "")),
                        severity="HIGH",
                        entropy=float(r.get("Entropy", 0.0)),
                        fingerprint=str(r.get("Fingerprint", "")),
                    ))
            except Exception as exc:  # noqa: BLE001
                parse_errors.append(f"Failed to parse gitleaks finding: {exc!r}")

        # Deterministic sorting: file -> line -> col -> rule_id
        findings.sort(key=lambda f: (f.file, f.line, f.col, f.rule_id))

        all_errors = scan_errors + parse_errors
        status = AnalyzerStatus.SUCCESS
        if parse_errors and not findings:
            status = AnalyzerStatus.FAILED
        elif parse_errors:
            status = AnalyzerStatus.PARTIAL

        return AnalyzerResult(
            status=status,
            results=[asdict(f) for f in findings],
            errors=all_errors if all_errors else [],
            provenance=self.provenance_tag,
            metadata={
                "gitleaks_version": GITLEAKS_VERSION,
                "findings": len(findings),
                "scan_errors": len(scan_errors),
            },
        )

    @staticmethod
    def _safe_env() -> Dict[str, str]:
        _SECRET_PREFIXES = (
            "GITLEAKS_",
            "SEMGREP_",
        )
        return {
            k: v for k, v in os.environ.items()
            if not any(k.upper().startswith(p) for p in _SECRET_PREFIXES)
        }


# Module-level singleton for GitleaksAnalyzer.
_GITLEAKS_ANALYZER = GitleaksAnalyzer()


@dataclass
class ExtractedDependency:
    """Dependency declared in a repository manifest file."""
    package_name: str
    installed_version: str
    ecosystem: str          # e.g., "PyPI", "npm"
    manifest_file: str      # relative path to manifest file


@dataclass
class OSVVulnerabilityFinding:
    """
    Normalized single OSV vulnerability finding.
    """
    package_name: str
    ecosystem: str
    installed_version: str
    vulnerability_id: str
    summary: str
    severity: str = "UNKNOWN"
    fixed_versions: List[str] = field(default_factory=list)
    affected_ranges: List[str] = field(default_factory=list)
    manifest_file: str = ""
    provenance: str = ""

    def __post_init__(self):
        if not self.provenance:
            self.provenance = "osv:v1.0.0"


def parse_manifest_file(abs_path: str, rel_path: str) -> tuple[List[ExtractedDependency], List[str]]:
    """
    Parses a single dependency manifest file safely without executing code.
    Returns (dependencies, errors).
    """
    filename = os.path.basename(abs_path).lower()
    errors: List[str] = []
    deps: List[ExtractedDependency] = []

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:  # noqa: BLE001
        return [], [f"Failed to read manifest {rel_path}: {exc!r}"]

    if ("requirements" in filename and filename.endswith(".txt")) or filename.endswith(".reqs"):
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            if ";" in line:
                line = line.split(";", 1)[0].strip()
            match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*(?:==|>=|<=|~=|>|<|!=)?\s*([A-Za-z0-9_\-\.]+)?", line)
            if match:
                pkg_name = match.group(1).strip()
                version = ""
                if "==" in line:
                    parts = line.split("==")
                    if len(parts) >= 2:
                        version = parts[1].split()[0].strip()
                elif match.group(2) and not any(op in line for op in (">=", "<=", "~=", ">", "<", "!=")):
                    version = match.group(2).strip()
                if pkg_name:
                    deps.append(ExtractedDependency(
                        package_name=pkg_name,
                        installed_version=version,
                        ecosystem="PyPI",
                        manifest_file=rel_path,
                    ))

    elif filename == "pyproject.toml" and tomllib:
        try:
            data = tomllib.loads(content)
            project_deps = data.get("project", {}).get("dependencies", [])
            if isinstance(project_deps, list):
                for item in project_deps:
                    if isinstance(item, str):
                        match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*(?:==|>=|<=|~=|>|<|!=)?\s*([A-Za-z0-9_\-\.]+)?", item.strip())
                        if match:
                            pkg_name = match.group(1).strip()
                            version = ""
                            if "==" in item:
                                parts = item.split("==")
                                if len(parts) >= 2:
                                    version = parts[1].split()[0].strip()
                            deps.append(ExtractedDependency(
                                package_name=pkg_name,
                                installed_version=version,
                                ecosystem="PyPI",
                                manifest_file=rel_path,
                            ))

            poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            if isinstance(poetry_deps, dict):
                for pkg_name, spec in poetry_deps.items():
                    if pkg_name.lower() == "python":
                        continue
                    version = ""
                    if isinstance(spec, str):
                        version = spec.lstrip("^~=>=")
                    elif isinstance(spec, dict) and "version" in spec:
                        version = str(spec["version"]).lstrip("^~=>=")
                    deps.append(ExtractedDependency(
                        package_name=pkg_name,
                        installed_version=version,
                        ecosystem="PyPI",
                        manifest_file=rel_path,
                    ))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to parse {rel_path} as TOML: {exc!r}")

    elif filename == "package.json":
        try:
            data = json.loads(content)
            for sec in ("dependencies", "devDependencies"):
                sec_data = data.get(sec, {})
                if isinstance(sec_data, dict):
                    for pkg_name, ver_spec in sec_data.items():
                        if isinstance(ver_spec, str):
                            clean_ver = ver_spec.lstrip("^~=>=")
                            deps.append(ExtractedDependency(
                                package_name=pkg_name,
                                installed_version=clean_ver,
                                ecosystem="npm",
                                manifest_file=rel_path,
                            ))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to parse {rel_path} as JSON: {exc!r}")

    return deps, errors


class OSVAnalyzer(BaseAnalyzer):
    """
    Dependency vulnerability analyzer backed by OSV.dev REST API.

    Security model
    --------------
    * Manifest files are treated as UNTRUSTED INPUT.
    * We NEVER execute package installers or repository code.
    * Outbound data is strictly bounded to package name, ecosystem, and version.
    * No secrets or code are transmitted to OSV.dev.
    * Subprocess timeouts and HTTP timeouts (30s) prevent DoS.

    Contract
    --------
      - unavailable  : Network / OSV service unreachable
      - unsupported  : No supported dependency manifest found in repository
      - success      : Scan completed cleanly (0 vulns OR 1+ vulns found)
      - partial      : Some manifests/queries failed but others succeeded
      - failed       : All queries failed, network error, or invalid API response
    """

    TIMEOUT_SECONDS: int = 30
    API_BATCH_URL: str = "https://api.osv.dev/v1/querybatch"
    API_VULN_URL: str = "https://api.osv.dev/v1/vulns/"

    def __init__(self) -> None:
        super().__init__(name="osv", version="1.0.0")

    def is_available(self) -> tuple[bool, Optional[str]]:
        return True, None

    def supports_language(self, language: str) -> bool:
        return True

    def _fetch_vuln_detail(self, vuln_id: str) -> dict:
        """Fetches detailed vulnerability object from OSV.dev /v1/vulns/{id}."""
        try:
            url = f"{self.API_VULN_URL}{vuln_id}"
            req = urllib.request.Request(url, headers={"User-Agent": "repo-analyzer/0.6.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
        return {}

    def analyze(self, repo_root: str, files: List[str]) -> AnalyzerResult:
        avail, err = self.is_available()
        if not avail:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                errors=[err] if err else [],
                provenance=self.provenance_tag,
                metadata={"reason": err or "OSV service unavailable"},
            )

        manifest_files = []
        for f in files:
            abs_p = f if os.path.isabs(f) else os.path.join(repo_root, f)
            fname = os.path.basename(abs_p).lower()
            if os.path.isfile(abs_p) and ((fname.endswith(".txt") and "requirements" in fname) or fname in ("pyproject.toml", "package.json")):
                rel_p = os.path.relpath(abs_p, repo_root).replace("\\", "/")
                manifest_files.append((abs_p, rel_p))

        for root, _, fnames in os.walk(repo_root):
            rel_root = os.path.relpath(root, repo_root)
            rel_parts = [p for p in rel_root.replace("\\", "/").split("/") if p and p != "."]
            if any(part.startswith(".") or part in ("venv", "node_modules", "__pycache__", "dist", "build") for part in rel_parts):
                continue
            for fname in fnames:
                flower = fname.lower()
                if (flower.endswith(".txt") and "requirements" in flower) or flower in ("pyproject.toml", "package.json"):
                    abs_p = os.path.join(root, fname)
                    rel_p = os.path.relpath(abs_p, repo_root).replace("\\", "/")
                    if (abs_p, rel_p) not in manifest_files:
                        manifest_files.append((abs_p, rel_p))

        if not manifest_files:
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "No supported dependency manifest found in repository"},
            )

        all_deps: List[ExtractedDependency] = []
        parse_errors: List[str] = []

        for abs_p, rel_p in sorted(manifest_files):
            deps, errs = parse_manifest_file(abs_p, rel_p)
            all_deps.extend(deps)
            parse_errors.extend(errs)

        if not all_deps:
            if parse_errors:
                return AnalyzerResult(
                    status=AnalyzerStatus.FAILED,
                    provenance=self.provenance_tag,
                    errors=parse_errors,
                )
            return AnalyzerResult(
                status=AnalyzerStatus.UNSUPPORTED,
                provenance=self.provenance_tag,
                metadata={"reason": "Dependency manifests exist but contain no parseable dependencies"},
            )

        dedup_dict: Dict[tuple, ExtractedDependency] = {}
        for d in all_deps:
            key = (d.manifest_file, d.ecosystem, d.package_name, d.installed_version)
            if key not in dedup_dict:
                dedup_dict[key] = d
        unique_deps = [dedup_dict[k] for k in sorted(dedup_dict.keys())]

        queries = []
        for d in unique_deps:
            q = {"package": {"name": d.package_name, "ecosystem": d.ecosystem}}
            if d.installed_version:
                q["version"] = d.installed_version
            queries.append(q)

        payload_bytes = json.dumps({"queries": queries}).encode("utf-8")
        req = urllib.request.Request(
            self.API_BATCH_URL,
            data=payload_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "repo-analyzer/0.6.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_SECONDS) as resp:
                resp_bytes = resp.read()
                resp_data = json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.URLError as exc:
            return AnalyzerResult(
                status=AnalyzerStatus.UNAVAILABLE,
                provenance=self.provenance_tag,
                errors=[f"OSV service network error: {exc}"],
            )
        except Exception as exc:  # noqa: BLE001
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[f"OSV batch query failed: {exc!r}"],
            )

        raw_results = resp_data.get("results", [])
        if not isinstance(raw_results, list) or len(raw_results) != len(unique_deps):
            return AnalyzerResult(
                status=AnalyzerStatus.FAILED,
                provenance=self.provenance_tag,
                errors=[f"OSV batch response mismatched queries count ({len(unique_deps)})"],
            )

        vuln_map: List[tuple[ExtractedDependency, dict]] = []
        unique_vuln_ids = set()

        for dep, res in zip(unique_deps, raw_results):
            if not isinstance(res, dict):
                continue
            for v in res.get("vulns", []):
                if isinstance(v, dict) and "id" in v:
                    vid = str(v["id"])
                    vuln_map.append((dep, v))
                    unique_vuln_ids.add(vid)

        details_cache: Dict[str, dict] = {}
        if unique_vuln_ids:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(unique_vuln_ids))) as executor:
                future_to_id = {executor.submit(self._fetch_vuln_detail, vid): vid for vid in list(unique_vuln_ids)[:30]}
                for future in concurrent.futures.as_completed(future_to_id):
                    vid = future_to_id[future]
                    try:
                        details_cache[vid] = future.result()
                    except Exception:  # noqa: BLE001
                        details_cache[vid] = {}

        findings: List[OSVVulnerabilityFinding] = []
        for dep, raw_v in vuln_map:
            vid = str(raw_v["id"])
            detail_obj = details_cache.get(vid, raw_v)

            summary = str(detail_obj.get("summary") or detail_obj.get("details") or "").split("\n")[0].strip()
            if not summary:
                summary = f"Vulnerability {vid}"

            severity_str = "UNKNOWN"
            if "severity" in detail_obj and isinstance(detail_obj["severity"], list):
                for s_entry in detail_obj["severity"]:
                    if isinstance(s_entry, dict) and "score" in s_entry:
                        severity_str = str(s_entry["score"])
                        break

            fixed_versions = []
            affected_ranges = []
            for aff in detail_obj.get("affected", []):
                for r_entry in aff.get("ranges", []):
                    r_type = r_entry.get("type", "")
                    events = r_entry.get("events", [])
                    event_strs = []
                    for ev in events:
                        if "introduced" in ev:
                            event_strs.append(f">= {ev['introduced']}")
                        if "fixed" in ev:
                            event_strs.append(f"< {ev['fixed']}")
                            if str(ev['fixed']) not in fixed_versions:
                                fixed_versions.append(str(ev['fixed']))
                    if event_strs:
                        affected_ranges.append(f"{r_type}: {', '.join(event_strs)}")

            findings.append(OSVVulnerabilityFinding(
                package_name=dep.package_name,
                ecosystem=dep.ecosystem,
                installed_version=dep.installed_version,
                vulnerability_id=vid,
                summary=summary,
                severity=severity_str,
                fixed_versions=sorted(fixed_versions),
                affected_ranges=sorted(affected_ranges),
                manifest_file=dep.manifest_file,
            ))

        findings.sort(key=lambda f: (f.manifest_file, f.package_name, f.vulnerability_id))

        status = AnalyzerStatus.SUCCESS
        if parse_errors and not findings:
            status = AnalyzerStatus.PARTIAL
        elif parse_errors:
            status = AnalyzerStatus.PARTIAL

        return AnalyzerResult(
            status=status,
            results=[asdict(f) for f in findings],
            errors=parse_errors,
            provenance=self.provenance_tag,
            metadata={
                "manifest_files_scanned": len(manifest_files),
                "dependencies_scanned": len(unique_deps),
                "vulnerabilities_found": len(findings),
                "parse_errors": len(parse_errors),
            },
        )


# Module-level singleton for OSVAnalyzer.
_OSV_ANALYZER = OSVAnalyzer()


class AnalyzerOrchestrator:
    """
    Centralized orchestration layer for analyzer execution across the pipeline.
    Coordinates Python-specific legacy analyzers (Radon CC, Radon MI, Bandit) and
    BaseAnalyzer instances (Lizard, Semgrep, Gitleaks, OSV.dev).
    """

    def __init__(self, repo_root: str, py_files_rel: List[str]) -> None:
        self.repo_root = repo_root
        self.py_files_rel = py_files_rel
        # Normalize files to relative paths first, safely handling both relative and absolute inputs
        self.rel_files = [
            os.path.relpath(f, repo_root).replace("\\", "/") if os.path.isabs(f) else f.replace("\\", "/")
            for f in py_files_rel
        ]
        self.prod_files = [f for f in self.rel_files if not is_test_file(f)]
        self.test_files = [f for f in self.rel_files if is_test_file(f)]
        self.abs_prod_files = [
            os.path.normpath(os.path.join(repo_root, f))
            for f in self.prod_files
        ]

    def run_radon(self) -> tuple[dict, dict]:
        complexity_results, maintainability_results = [], []
        any_complexity_failure = any_maintainability_failure = False

        for rel in self.prod_files:
            abs_path = os.path.join(self.repo_root, rel)
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

        comp_dict = {"status": complexity_status, "results": [asdict(c) for c in complexity_results]}
        maint_dict = {"status": maintainability_status, "results": [asdict(m) for m in maintainability_results]}
        return comp_dict, maint_dict

    def run_bandit(self) -> dict:
        security_status, security_results = run_bandit(self.repo_root, self.prod_files)
        return {"status": security_status, "results": [asdict(s) for s in security_results]}

    def execute_all(self) -> dict:
        if not self.py_files_rel:
            return {
                "scope_policy": "production_code_only",
                "production_files_analyzed": 0,
                "test_files_excluded": 0,
                "complexity": {"status": "unsupported", "results": []},
                "maintainability": {"status": "unsupported", "results": []},
                "security": {"status": "unsupported", "results": []},
                "lizard_complexity": {"status": "unsupported", "results": []},
                "semgrep_findings": {"status": "unsupported", "results": []},
                "gitleaks_findings": {"status": "unsupported", "results": []},
                "osv_vulnerabilities": {"status": "unsupported", "results": []},
            }

        comp_dict, maint_dict = self.run_radon()
        sec_dict = self.run_bandit()

        base_analyzers: Dict[str, BaseAnalyzer] = {
            "lizard_complexity": _LIZARD_ANALYZER,
            "semgrep_findings": _SEMGREP_ANALYZER,
            "gitleaks_findings": _GITLEAKS_ANALYZER,
            "osv_vulnerabilities": _OSV_ANALYZER,
        }

        analysis_output = {
            "scope_policy": "production_code_only",
            "production_files_analyzed": len(self.prod_files),
            "test_files_excluded": len(self.test_files),
            "complexity": comp_dict,
            "maintainability": maint_dict,
            "security": sec_dict,
        }

        for key, analyzer in base_analyzers.items():
            result = analyzer.analyze(self.repo_root, self.abs_prod_files)
            analysis_output[key] = result.to_dict()

        return analysis_output


def analyze_repository(repo_root: str, py_files_rel: list) -> dict:
    """
    py_files_rel: ALL python files found (test + production).
    Orchestrates Radon, Bandit, Lizard, Semgrep, Gitleaks, and OSV analyzers cleanly.
    """
    orchestrator = AnalyzerOrchestrator(repo_root, py_files_rel)
    return orchestrator.execute_all()

