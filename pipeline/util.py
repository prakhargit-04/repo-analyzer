"""
Shared, single-source-of-truth utilities so that "is this a test file" and
"what identifies this snapshot of the repo" are decided ONCE and used
identically everywhere -- the previous version's bug (tests excluded from
bandit but not from radon) was exactly two copies of similar-but-different
logic drifting apart. There is now exactly one function for each.
"""
from __future__ import annotations
import hashlib
import os
import subprocess
from pathlib import Path

TEST_PATH_MARKERS = ("test/", "tests/", "testing/", "/test/", "/tests/", "/testing/")
TEST_SUPPORT_FILENAMES = {"conftest.py"}

IGNORED_SNAPSHOT_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build"}

# Bumped whenever the cache *schema* (result JSON shape) or the analyzer's
# *behavior* (parser, scoring formula, test-exclusion policy, graph
# resolution rules) changes -- so an old cached result from before a bugfix
# can never be served as if it reflects the fixed code. Snapshot identity
# alone is not enough for this: the repo content didn't change, the
# analyzer did.
CACHE_SCHEMA_VERSION = "v4"  # bumped: Session 1 schema freeze v1.0.0
SCHEMA_VERSION = "1.0.0"
ANALYZER_VERSION = "0.10.0"  # bumped: Session 10 — Tree-sitter JS/TS parser integration


def is_test_file(rel_path: str) -> bool:
    """Single definition of 'this is a test file', used by every stage that
    needs to decide whether to include or exclude it. Verified against real
    repos rather than assumed: `tests/`/`test/` covers most projects, but
    pytest's `conftest.py` (test fixtures, lives at any level, doesn't
    match test_*/*_test.py) and a `testing/` directory name (used by e.g.
    pytest-dev/iniconfig itself) both slipped through an earlier version of
    this function during validation -- fixed here, not just assumed correct."""
    norm = rel_path.replace("\\", "/")
    if not norm.startswith("/"):
        norm = "/" + norm
    if any(marker in norm for marker in TEST_PATH_MARKERS):
        return True
    basename = os.path.basename(rel_path)
    if basename in TEST_SUPPORT_FILENAMES:
        return True
    return basename.startswith("test_") or basename.endswith("_test.py")


def resolve_snapshot_id(repo_root: str, is_fresh_clone: bool, git_sha: str | None) -> str:
    """
    Returns a cache key that is actually correct for the case it's used in:

    - Fresh clone (this process just ran `git clone`): the resolved git SHA
      is trustworthy because nothing can have modified the checkout between
      clone and analysis. Cheap and correct.
    - Local path (user-supplied, possibly a working copy with uncommitted
      edits, possibly not a git repo at all): git HEAD SHA is NOT sufficient
      -- a dirty working tree changes the actual content without changing
      HEAD. Instead, this hashes the actual BYTES of every included file
      (plus its relative path, so moving identical content to a different
      path also changes the snapshot).

      A previous version of this fallback hashed relative-path + file-size
      + mtime instead of file content. That is not a content hash: two
      different file bodies of the same size can collide, and more
      practically, two edits that happen to preserve file size (or that
      land within the same integer second, depending on filesystem mtime
      resolution) could invalidate nothing. Reading and hashing the actual
      bytes is the only way to make this claim true.
    """
    if is_fresh_clone and git_sha:
        return git_sha

    hasher = hashlib.sha256()
    root = Path(repo_root)

    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and not any(part in IGNORED_SNAPSHOT_DIRS for part in p.relative_to(root).parts)
    )

    for path in files:
        rel = path.relative_to(root).as_posix()

        # Path matters: identical bytes at a different path is a real change.
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")

        try:
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    hasher.update(chunk)
        except OSError:
            # unreadable file (broken symlink, permissions) -- still record
            # that a file existed at this path so removing/breaking it
            # changes the snapshot, without crashing the whole pipeline.
            hasher.update(b"<unreadable>")

        hasher.update(b"\0")

    return f"content-sha256:{hasher.hexdigest()}"


def build_cache_key(snapshot_id: str) -> str:
    """
    The repository snapshot alone is an insufficient cache key: it says
    nothing about whether the *analyzer's own behavior* changed since the
    cached result was written (parser rules, scoring formula, test-exclusion
    policy, graph-resolution logic, result schema). Folding in a schema
    version and an analyzer version means a bugfix to this codebase
    invalidates old cache entries even when the repository content being
    analyzed hasn't changed at all -- otherwise a stale cache hit could
    silently keep serving pre-fix (wrong) results forever.

    Deliberately excludes anything that changes on every run (timestamps,
    process ids, etc) -- a cache key must be reproducible for identical
    (analyzer_version, repo_content) pairs.
    """
    raw = f"{CACHE_SCHEMA_VERSION}\n{ANALYZER_VERSION}\n{snapshot_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def try_git_head_sha(path: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
