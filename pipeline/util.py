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
import time
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
CACHE_SCHEMA_VERSION = "v5"  # bumped: Session 24 Semgrep penalty & schema updates
SCHEMA_VERSION = "1.0.0"
from version import APP_VERSION
ANALYZER_VERSION = APP_VERSION


def is_safe_relative_path(rel_path: str, repo_root: str) -> bool:
    """Verifies that rel_path does not attempt path traversal outside repo_root."""
    try:
        full_path = os.path.abspath(os.path.join(repo_root, rel_path))
        root_path = os.path.abspath(repo_root)
        return os.path.commonpath([full_path, root_path]) == root_path
    except Exception:
        return False


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
    nothing about whether the *analyzer's own behavior*, *source chunker*, or
    *embedding provider* changed since the cached result was written. Folding in
    schema, analyzer, chunker, and embedding version strings invalidates old cache entries.
    Derives key from configuration only without instantiating ML models.
    """
    from chunker import SOURCE_CHUNKER_VERSION
    from embeddings import EMBEDDING_PIPELINE_VERSION, get_embedding_provider_info
    p_name, p_version = get_embedding_provider_info()
    raw = f"{CACHE_SCHEMA_VERSION}\n{ANALYZER_VERSION}\n{SOURCE_CHUNKER_VERSION}\n{EMBEDDING_PIPELINE_VERSION}\n{p_name}\n{p_version}\n{snapshot_id}"
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


def get_cache_dir() -> str:
    """
    Single source of truth for the analysis cache directory.
    If CACHE_DIR env var is set, return its absolute path.
    Otherwise default to <repo_root>/.cache (absolute path).
    """
    env_dir = os.environ.get("CACHE_DIR", "").strip()
    if env_dir:
        return os.path.abspath(env_dir)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.abspath(os.path.join(repo_root, ".cache"))


def is_dangerous_cache_path(path: str) -> bool:
    """Check if resolved cache path is dangerously high up (root, home, repo_root)."""
    try:
        abs_path = os.path.abspath(path)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        home_dir = os.path.abspath(os.path.expanduser("~"))

        if abs_path in ("/", "\\") or os.path.dirname(abs_path) == abs_path:
            return True
        if abs_path == home_dir:
            return True
        if abs_path == repo_root:
            return True
        return False
    except Exception:
        return True


def cleanup_cache(cache_dir: str, max_age_days: int | None, max_total_mb: int | None) -> dict[str, int]:
    """Delete eligible cache files by age, then oldest-first to meet size cap."""
    result = {"deleted_files": 0, "deleted_bytes": 0}
    if not cache_dir or is_dangerous_cache_path(cache_dir):
        import logging
        logging.getLogger("repo_analyzer_api").warning("Refusing cache cleanup on dangerous path '%s'", cache_dir)
        return result

    root = Path(cache_dir)
    if not root.is_dir():
        return result
    now = time.time()
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.endswith(".tmp") and now - p.stat().st_mtime >= 3600]
    def remove(path: Path) -> None:
        try:
            size = path.stat().st_size
            path.unlink()
            result["deleted_files"] += 1
            result["deleted_bytes"] += size
        except OSError:
            pass
    if max_age_days is not None:
        cutoff = now - max(0, max_age_days) * 86400
        for path in files:
            if path.stat().st_mtime < cutoff:
                remove(path)
    files = [p for p in files if p.exists()]
    if max_total_mb is not None:
        limit = max(0, max_total_mb) * 1024 * 1024
        total = sum(p.stat().st_size for p in files)
        for path in sorted(files, key=lambda p: p.stat().st_mtime):
            if total <= limit:
                break
            size = path.stat().st_size
            remove(path)
            total -= size
    return result


def working_tree_size_bytes(path: str) -> int:
    """
    Computes total size of regular files in a working tree directory.
    - Excludes '.git' directories at any depth.
    - Skips symlinks, sockets, devices, FIFOs, and unreadable files.
    - Uses os.lstat (followlinks=False) so dangling/outside symlinks never cause errors or false size count.
    """
    import stat
    total_size = 0
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return 0

    for root, dirs, files in os.walk(abs_path, followlinks=False):
        if ".git" in dirs:
            dirs.remove(".git")
        for file_name in files:
            file_path = os.path.join(root, file_name)
            try:
                st = os.lstat(file_path)
                if stat.S_ISREG(st.st_mode):
                    total_size += st.st_size
            except OSError:
                continue
    return total_size
