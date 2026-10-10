"""
Server-side GitHub HTTPS URL validator for the API submission endpoint (S22).

This validator is ONLY applied at the API layer (routes.py), NOT inside
clone.py.  clone.py retains its broader permissiveness because CLI usage
and tests legitimately use local paths and file:// fixtures.

Accepted URL form:
  https://github.com/<owner>/<repo>
  https://github.com/<owner>/<repo>.git
  https://github.com/<owner>/<repo>/    (trailing slash stripped)

Rejected:
  - Any non-https scheme (http://, git://, git@, ssh://, file://)
  - Non-GitHub hosts (including userinfo tricks: user@github.com, github.com@evil.com)
  - Non-default ports
  - Localhost / 127.x.x.x / private / link-local IPs
  - Empty, whitespace-only, or control-character-containing inputs
  - Inputs starting with '-' (git option injection)
  - Extra path segments beyond /<owner>/<repo>
  - Query strings or fragments
  - Owner or repo names that are empty, start with '-', or contain disallowed chars
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

# Strict GitHub HTTPS prefix — no userinfo, no port
_GITHUB_HTTPS_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

# Deny any whitespace or ASCII control characters in the raw input
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\s]")

# Owner/repo segment must not start with '-' (git option injection guard)
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def validate_github_url(url: str) -> tuple[bool, str]:
    """
    Validate that `url` is a well-formed, GitHub-hosted, HTTPS-only repository URL.

    Returns:
        (True, normalized_url)  — if valid.
        (False, reason_string)  — if invalid; reason is safe to return in HTTP 422 response.

    This function does NOT make any network calls.
    """
    if not url:
        return False, "Repository URL must not be empty."

    if len(url) > 2048:
        return False, "Repository URL exceeds maximum length of 2048 characters."

    # Reject percent-encoding or raw control characters / whitespace
    if "%" in url:
        return False, "Repository URL must not contain percent-encoded characters."

    # Reject whitespace / control characters
    if _CONTROL_RE.search(url):
        return False, "Repository URL must not contain whitespace or control characters."

    # Reject git-option injection: inputs starting with '-'
    if url.lstrip().startswith("-"):
        return False, "Repository URL must not start with '-'."

    # Parse the URL
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "Repository URL is not parseable."

    # Scheme must be https (case-insensitive)
    if parsed.scheme.lower() != "https":
        return False, (
            f"Only HTTPS GitHub URLs are accepted (got scheme '{parsed.scheme}'). "
            "Rejected: http://, git://, git@, ssh://, file://, and local paths."
        )

    # No userinfo (catches https://user@github.com/x or https://github.com@evil.com/x)
    if parsed.username or parsed.password:
        return False, "Repository URL must not contain userinfo (username/password)."

    # Host must be exactly github.com (case-insensitive)
    host = (parsed.hostname or "").lower()
    if host != "github.com":
        return False, (
            f"Only github.com repositories are accepted (got host '{host}'). "
            "Localhost, private IPs, and non-GitHub hosts are rejected."
        )

    # No non-default port
    if parsed.port is not None:
        return False, f"Repository URL must not specify a port (got :{parsed.port})."

    # No query string or fragment
    if parsed.query:
        return False, "Repository URL must not contain a query string."
    if parsed.fragment:
        return False, "Repository URL must not contain a URL fragment."

    # Match the full path pattern
    m = _GITHUB_HTTPS_RE.match(url.strip())
    if not m:
        return False, (
            "Repository URL must have exactly the form "
            "https://github.com/<owner>/<repo> (optional .git or trailing slash). "
            "Extra path segments are not accepted."
        )

    owner, repo = m.group(1), m.group(2)

    # Owner/repo must not be empty and must not start with '-'
    if not owner or not _SEGMENT_RE.match(owner):
        return False, f"Invalid repository owner name: '{owner}'."
    if not repo or not _SEGMENT_RE.match(repo):
        return False, f"Invalid repository name: '{repo}'."

    # Normalize: strip trailing slash and .git for canonical form
    normalized = f"https://github.com/{owner}/{repo}"
    return True, normalized
