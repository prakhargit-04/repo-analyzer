"""Stage 1: clone / checkout a repository at a specific commit SHA (or default branch)."""
from __future__ import annotations
import os
import re
import shutil
import subprocess

MAX_CLONE_TIMEOUT = 300  # 5 minutes
MAX_CHECKOUT_TIMEOUT = 60  # 1 minute

HEX_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Applied to EVERY git invocation that touches a repository we did not create.
#   core.hooksPath=/dev/null        repository hooks never run
#   protocol.ext.allow=never        no ext:: command transports
#   http.followRedirects=false      a redirect to another host fails instead of being followed
#   submodule.recurse=false         submodules are never fetched implicitly
_HARDENED_GIT_CONFIG = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "protocol.ext.allow=never",
    "-c", "http.followRedirects=false",
    "-c", "submodule.recurse=false",
)


def _git_env() -> dict:
    """Environment for git subprocesses: never prompt for credentials."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"   # a credential helper that returns nothing -> auth fails fast
    env.pop("SSH_ASKPASS", None)
    return env


def is_safe_repo_url(url: str) -> bool:
    """Validate repository URL to prevent flag injection or unsafe protocols."""
    url_clean = url.strip()
    if not url_clean or url_clean.startswith("-"):
        return False
    return (
        url_clean.startswith(("https://", "http://", "git@", "file://", "git://"))
        or (os.path.exists(url_clean) and not os.path.basename(url_clean).startswith("-"))
    )


def is_remote_repo_url(url: str) -> bool:
    """Validate that URL is a remote Git repository URL (rejects local file paths for API)."""
    url_clean = url.strip()
    if not url_clean or url_clean.startswith("-"):
        return False
    return url_clean.startswith(("https://", "http://", "git@", "git://"))


def resolve_remote_sha(repo_url: str) -> str | None:
    """Resolve HEAD commit SHA of a remote repository using git ls-remote without cloning."""
    if not is_remote_repo_url(repo_url):
        return None

    cmd = [
        "git",
        *_HARDENED_GIT_CONFIG,
        "ls-remote",
        "--quiet",
        "--",
        repo_url,
        "HEAD",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=_git_env())
        if res.returncode == 0 and res.stdout:
            parts = res.stdout.strip().split()
            if parts and HEX_SHA_PATTERN.match(parts[0]):
                return parts[0]
    except Exception:
        pass
    return None



def _redact_url(url: str) -> str:
    """Remove any user:password@ part so credentials never reach an error message or log."""
    return re.sub(r"(?<=//)[^/@\s]+@", "***@", url or "")


def _clone_failure_reason(exc: BaseException) -> str:
    """Human-useful, non-leaking reason for a failed clone.

    Never includes the git argv, the destination path, raw stderr, or URL credentials: those
    reach API clients through the job error_message.
    """
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"git timed out after {int(exc.timeout)} seconds"
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = (exc.stderr or "").lower() if isinstance(exc.stderr, str) else ""
        in_checkout = isinstance(exc.cmd, (list, tuple)) and "checkout" in exc.cmd
        if "redirect" in stderr or "unable to update url base" in stderr or re.search(r"error: 30[12378]\b", stderr):
            return "the repository URL redirected and redirects are not followed; use the canonical repository URL"
        if in_checkout or any(k in stderr for k in ("unknown revision", "not a commit", "bad object", "pathspec")):
            return "the requested commit was not found in the repository"
        if any(k in stderr for k in ("not found", "does not appear to be a git repository", "could not read from remote")):
            return "repository not found or not accessible (private repositories are not supported)"
        if any(k in stderr for k in ("could not resolve host", "unable to access", "connection", "timed out")):
            return "the repository host could not be reached"
        return f"git exited with status {exc.returncode}"
    if isinstance(exc, RuntimeError):
        return str(exc)  # raised by this module itself with a fixed, safe message
    return f"unexpected error ({type(exc).__name__})"


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
        *_HARDENED_GIT_CONFIG,
        "clone",
        "--quiet",
        "--no-recurse-submodules",
    ]
    if not commit_sha:
        # Only the tip is needed. A pinned SHA may not be the tip, so that case
        # keeps full history (checkout below would otherwise fail).
        clone_cmd += ["--depth", "1"]
    clone_cmd += ["--", repo_url, dest_dir]

    try:
        subprocess.run(clone_cmd, check=True, timeout=MAX_CLONE_TIMEOUT, capture_output=True, text=True, env=_git_env())

        if commit_sha:
            checkout_cmd = [
                "git",
                "-C", dest_dir,
                *_HARDENED_GIT_CONFIG,
                "checkout",
                "--quiet",
                commit_sha,
            ]
            subprocess.run(checkout_cmd, check=True, timeout=MAX_CHECKOUT_TIMEOUT, capture_output=True, text=True, env=_git_env())

        resolved = subprocess.run(
            ["git", "-C", dest_dir, "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()

        if not HEX_SHA_PATTERN.match(resolved):
            raise RuntimeError(f"Failed to resolve valid HEAD commit SHA, got: '{resolved}'")

        repo_max_mb_raw = os.environ.get("REPO_MAX_MB", "").strip()
        max_mb = None
        if repo_max_mb_raw:
            try:
                val = int(repo_max_mb_raw)
                if val < 0:
                    raise ValueError
                max_mb = val
            except ValueError:
                import logging
                logging.getLogger("repo_analyzer_api").warning(
                    "Invalid REPO_MAX_MB value '%s'; disabling size check", repo_max_mb_raw
                )
                max_mb = None

        if max_mb is not None and max_mb > 0:
            from util import working_tree_size_bytes
            size = working_tree_size_bytes(dest_dir)
            if size > max_mb * 1024 * 1024:
                raise RuntimeError("Repository working tree exceeds configured size limit")

        return resolved

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as exc:
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        raise RuntimeError(
            f"Failed to clone repository '{_redact_url(repo_url)}': {_clone_failure_reason(exc)}"
        ) from None
