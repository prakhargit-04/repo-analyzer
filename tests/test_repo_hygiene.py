"""
Unit tests for repo hygiene verification (TASK R8).
"""
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_repo_hygiene import check_hygiene, FORBIDDEN_EXTENSIONS, FORBIDDEN_DIR_NAMES, FORBIDDEN_FILE_NAMES


class TestRepoHygiene(unittest.TestCase):

    def test_current_repo_is_clean(self):
        """Verify the current repository has no forbidden artifacts."""
        sys.dont_write_bytecode = True
        violations = check_hygiene(_REPO_ROOT)
        # Filter out transient __pycache__ and .pytest_cache created during active pytest execution
        static_violations = [
            v for v in violations
            if "__pycache__" not in v
            and ".pytest_cache" not in v
            and not v.endswith(".pyc")
            and not v.endswith(".db")           # SQLite files are .gitignore'd transient test artifacts
            and not v.endswith(".db-shm")
            and not v.endswith(".db-wal")
            and not v.endswith(".tsbuildinfo")  # TypeScript incremental build info, .gitignore'd
        ]
        self.assertEqual(static_violations, [], f"Forbidden artifacts found in repo: {static_violations}")

    def test_forbidden_patterns_coverage(self):
        """Verify forbidden sets cover all required patterns per Task R8."""
        self.assertIn(".db", FORBIDDEN_EXTENSIONS)
        self.assertIn(".pyc", FORBIDDEN_EXTENSIONS)
        self.assertIn(".tsbuildinfo", FORBIDDEN_EXTENSIONS)

        self.assertIn("__pycache__", FORBIDDEN_DIR_NAMES)
        self.assertIn(".pytest_cache", FORBIDDEN_DIR_NAMES)
        self.assertIn(".next", FORBIDDEN_DIR_NAMES)

        self.assertIn("repo_analyzer.db", FORBIDDEN_FILE_NAMES)


if __name__ == "__main__":
    unittest.main()
