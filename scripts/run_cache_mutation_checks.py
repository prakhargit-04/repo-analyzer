#!/usr/bin/env python
"""Mutation checks for the cache-fingerprint and force-refresh logic.

Each mutation deliberately breaks one cache guard in a TEMPORARY COPY of the repository
(the working tree is never modified, so nothing needs restoring, even on Ctrl-C).
For every mutation the harness:

  1. verifies the mutation changed exactly one occurrence of its target text,
  2. confirms the baseline (unmutated) run of the focused tests passes first,
  3. requires the specific named tests below to FAIL (not merely any non-zero exit),
     and rejects collection/import errors as a false "kill".

Usage:  python scripts/run_cache_mutation_checks.py        (exit 0 = all mutations killed)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEST_FILES = [
    "tests/test_cache_fingerprint.py",
    "tests/test_force_refresh.py",
    "tests/test_analysis_config_fingerprint_unit.py",
    "tests/test_cache_compatibility.py",
]
CF = "tests/test_cache_fingerprint.py::"
FR = "tests/test_force_refresh.py::"
UNIT = "tests/test_analysis_config_fingerprint_unit.py::"
CC = "tests/test_cache_compatibility.py::"

# name -> (file, exact text to replace (must occur once), replacement, tests that must fail)
MUTATIONS = [
    ("M1 drop DB fingerprint comparison", "pipeline/db/store.py",
     "        .where(AnalysisRun.config_fingerprint == current_fingerprint)\n", "",
     {CF + "test_db_cache_invalidated_when_semgrep_rules_change",
      CF + "test_db_cache_invalidated_when_model_changes_same_dimension",
      CF + "test_db_cache_invalidated_when_chunker_version_changes",
      CF + "test_legacy_null_fingerprint_is_not_reused"}),
    ("M2a force_refresh does not bypass DB cache (route)", "pipeline/api/routes.py",
     "if effective_sha and not req.force_refresh:", "if effective_sha:",
     {FR + "test_force_refresh_persists_flag_skips_cache_and_creates_new_run",
      FR + "test_force_refresh_does_not_duplicate_chunks_or_embeddings",
      FR + "test_force_refresh_replaces_partial_with_new_complete_run"}),
    ("M2b force_refresh does not bypass file cache (worker)", "pipeline/worker.py",
     "use_cache=not force_refresh,", "use_cache=True,",
     {FR + "test_force_refresh_persists_flag_skips_cache_and_creates_new_run",
      FR + "test_force_refresh_replaces_partial_with_new_complete_run"}),
    ("M3 ignore Semgrep ruleset identity", "pipeline/util.py",
     'raw = (os.environ.get("SEMGREP_CONFIG") or "").strip()', 'raw = ""',
     {CF + "test_fingerprint_changes_when_ruleset_contents_change",
      CF + "test_db_cache_invalidated_when_semgrep_rules_change",
      UNIT + "test_fingerprint_tracks_rules_content_and_auto_default",
      CC + "test_file_cache_key_depends_on_the_semgrep_ruleset",
      CC + "test_file_cache_key_for_a_rules_directory_tracks_every_file"}),
]
BAD_REASONS = ("ModuleNotFoundError", "ImportError", "SyntaxError", "IndentationError", "NameError")


def run_tests(cwd: Path) -> tuple[int, str, set[str], set[str]]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-q", "-rfE", "-p", "no:cacheprovider", "--timeout=120"],
        cwd=cwd, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    failed = {m.group(1) for m in re.finditer(r"^FAILED (\S+)", out, re.M)}
    errored = {m.group(1) for m in re.finditer(r"^ERROR (\S+)", out, re.M)}
    return proc.returncode, out, failed, errored


def main() -> int:
    ok = True
    ignore = shutil.ignore_patterns("node_modules", "__pycache__", ".cache", "*.db", ".next", ".git")
    for name, rel, old, new, expected in [("BASELINE", "", "", "", set())] + MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="mutation_") as tmp:
            work = Path(tmp) / "repo"
            shutil.copytree(ROOT, work, ignore=ignore)
            if rel:
                target = work / rel
                text = target.read_text(encoding="utf-8")
                if text.count(old) != 1:
                    print(f"[FAIL] {name}: target text found {text.count(old)}x in {rel} (need exactly 1)")
                    ok = False
                    continue
                mutated = text.replace(old, new)
                if mutated == text:
                    print(f"[FAIL] {name}: mutation did not change {rel}")
                    ok = False
                    continue
                target.write_text(mutated, encoding="utf-8")
            code, out, failed, errored = run_tests(work)
            if not rel:  # baseline must be fully green
                good = code == 0 and not failed and not errored
                print(f"[{'PASS' if good else 'FAIL'}] baseline: focused tests pass unmutated "
                      f"({out.strip().splitlines()[-1] if out.strip() else 'no output'})")
                ok = ok and good
                if not good:
                    print("       baseline must pass before mutations are meaningful; aborting")
                    return 1
                continue
            missing = expected - failed
            bad = [r for r in BAD_REASONS if r in out]
            good = not missing and not errored and not bad
            print(f"[{'KILLED' if good else 'SURVIVED/INVALID'}] {name}: {len(failed)} test(s) failed, "
                  f"{len(expected)} required")
            for t in sorted(missing):
                print(f"       expected failure did not occur: {t}")
            if errored or bad:
                print(f"       invalid kill (collection/import error): errors={sorted(errored)} reasons={bad}")
            ok = ok and good
    print("\nAll mutations killed." if ok else "\nMutation checks FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
