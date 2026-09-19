"""Stage 1: clone / checkout a repository at a specific commit SHA (or default branch)."""
from __future__ import annotations
import os
import re
import shutil
import subprocess

MAX_CLONE_TIMEOUT = 300  # 5 minutes
MAX_CHECKOUT_TIMEOUT = 60  # 1 minute

HEX_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


def is_safe_repo_url(url: str) -> bool:
    """Validate repository URL to prevent flag injection or unsafe protocols."""
    url_clean = url.strip()
    if not url_clean or url_clean.startswith("-"):
        return False
    return (
        url_clean.startswith(("https://", "http://", "git@", "file://", "git://"))
        or (os.path.exists(url_clean) and not os.path.basename(url_clean).startswith("-"))
    )


def clone_repository(repo_url: str, dest_dir: str, commit_sha: str | None = None) -> str:
    """Clones repo_url into dest_dir safely. If commit_sha is given, checks it out.
    Returns the resolved commit SHA actually checked out (for cache-keying)."""
    if not is_safe_repo_url(repo_url):
        raise ValueError(f"Invalid or unsafe repository URL: '{repo_url}'")

    if os.path.exists(dest_dir):
        if os.listdir(dest_dir):
            raise FileExistsError(f"{dest_dir} already exists and is not empty")
    else:
        os.makedirs(dest_dir, exist_ok=True)

    if commit_sha and not HEX_SHA_PATTERN.match(commit_sha):
        raise ValueError(f"Invalid commit SHA format: '{commit_sha}'")

    clone_cmd = [
        "git",
        "-c", "core.hooksPath=/dev/null",
        "-c", "protocol.ext.allow=never",
        "clone",
        "--quiet",
        "--",
        repo_url,
        dest_dir,
    ]

    try:
        subprocess.run(clone_cmd, check=True, timeout=MAX_CLONE_TIMEOUT, capture_output=True, text=True)

        if commit_sha:
            checkout_cmd = [
                "git",
                "-C", dest_dir,
                "-c", "core.hooksPath=/dev/null",
                "checkout",
                "--quiet",
                "--",
                commit_sha,
            ]
            subprocess.run(checkout_cmd, check=True, timeout=MAX_CHECKOUT_TIMEOUT, capture_output=True, text=True)

        resolved = subprocess.run(
            ["git", "-C", dest_dir, "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()

        if not HEX_SHA_PATTERN.match(resolved):
            raise RuntimeError(f"Failed to resolve valid HEAD commit SHA, got: '{resolved}'")

        return resolved

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as exc:
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to clone repository '{repo_url}': {exc}") from exc
