"""Stage 1: clone / checkout a repository at a specific commit SHA (or default branch)."""
from __future__ import annotations
import subprocess
import os


def clone_repository(repo_url: str, dest_dir: str, commit_sha: str | None = None) -> str:
    """Clones repo_url into dest_dir. If commit_sha is given, checks it out.
    Returns the resolved commit SHA actually checked out (for cache-keying)."""
    if os.path.exists(dest_dir):
        raise FileExistsError(f"{dest_dir} already exists; pass a fresh directory")

    subprocess.run(["git", "clone", "--quiet", repo_url, dest_dir], check=True, timeout=300)

    if commit_sha:
        subprocess.run(["git", "-C", dest_dir, "checkout", "--quiet", commit_sha], check=True, timeout=60)

    resolved = subprocess.run(
        ["git", "-C", dest_dir, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=30,
    ).stdout.strip()

    return resolved
