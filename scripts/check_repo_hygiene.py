"""
Repo Hygiene Checker for Repo Analyzer v0.24.2 (TASK R8).

Asserts that no forbidden build artifacts, caches, compiled files, or temporary databases
exist in git tracking or in the workspace.

Supports --clean flag to remove forbidden temporary files.
Exits with 0 on clean repository, 1 if any forbidden files remain.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_EXTENSIONS = {
    ".db",
    ".db-journal",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite3",
    ".pyc",
    ".pyo",
    ".pyd",
    ".tsbuildinfo",
}

FORBIDDEN_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".coverage",
    "htmlcov",
    "dist",
    "build",
}

FORBIDDEN_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "repo_analyzer.db",
}


def get_tracked_files(repo_root: Path) -> list[Path]:
    """Get list of files tracked by git, or all files excluding node_modules/.venv if not git repo."""
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return [repo_root / line for line in lines]
    except Exception:
        tracked = []
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in ("node_modules", ".venv", ".git")]
            for f in files:
                tracked.append(Path(root) / f)
        return tracked


def check_hygiene(repo_root: Path = _REPO_ROOT) -> list[str]:
    """Check repository files against forbidden patterns. Returns list of offending file paths."""
    offending = []
    files_to_check = get_tracked_files(repo_root)

    for p in files_to_check:
        try:
            rel = p.relative_to(repo_root)
        except ValueError:
            continue
        parts = rel.parts

        if any(part in FORBIDDEN_DIR_NAMES for part in parts[:-1]):
            offending.append(str(rel))
            continue

        if p.name in FORBIDDEN_FILE_NAMES:
            offending.append(str(rel))
            continue

        if p.suffix.lower() in FORBIDDEN_EXTENSIONS:
            offending.append(str(rel))
            continue

    return offending


def clean_repository(repo_root: Path = _REPO_ROOT):
    """Clean up unversioned build artifacts and cache directories."""
    removed_count = 0
    for root, dirs, files in os.walk(repo_root, topdown=False):
        if "node_modules" in root or ".venv" in root or ".git" in root:
            continue
        for d in dirs:
            if d in FORBIDDEN_DIR_NAMES:
                d_path = Path(root) / d
                try:
                    shutil.rmtree(d_path, ignore_errors=True)
                    removed_count += 1
                except Exception:
                    pass
        for f in files:
            p_path = Path(root) / f
            if f in FORBIDDEN_FILE_NAMES or p_path.suffix.lower() in FORBIDDEN_EXTENSIONS:
                try:
                    p_path.unlink(missing_ok=True)
                    removed_count += 1
                except Exception:
                    pass
    print(f"Cleaned up {removed_count} temporary build/cache items.")


def main():
    if "--clean" in sys.argv:
        clean_repository(_REPO_ROOT)

    print(f"Checking repository hygiene for: {_REPO_ROOT}")
    violations = check_hygiene(_REPO_ROOT)

    if violations:
        print("\n[FAIL] HYGIENE VIOLATION DETECTED! The following forbidden files were found:")
        for v in violations[:30]:
            print(f"  - {v}")
        if len(violations) > 30:
            print(f"  ... and {len(violations) - 30} more.")
        sys.exit(1)
    else:
        print("\n[OK] REPOSITORY IS CLEAN! Zero forbidden artifacts found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
