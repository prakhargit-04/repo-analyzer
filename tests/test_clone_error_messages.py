"""
v0.24.6 final refinement - clone failures must be USEFUL and must not LEAK.

Before this fix the job error_message served by the API was ``str(CalledProcessError)``: the full git
argv (hardening flags, the server's temp checkout path, the URL) and no reason. These tests pin the
contract: a stable "Failed to clone repository '<url>': <reason>" with a human reason, and never the
argv, the destination path, git's raw stderr, or URL credentials.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

import clone  # noqa: E402

LEAKS = ["core.hooksPath", "http.followRedirects", "protocol.ext", "Command [", "/dev/null", "--no-recurse"]


def _assert_clean(msg: str, dest) -> None:
    assert msg.startswith("Failed to clone repository"), msg
    for leak in LEAKS:
        assert leak not in msg, f"{leak!r} leaked into: {msg}"
    assert str(dest) not in msg, f"destination path leaked into: {msg}"
    assert "Traceback" not in msg


def test_missing_repository_gives_a_reason_and_leaks_no_argv_or_path(tmp_path):
    dest = tmp_path / "checkout"
    with pytest.raises(RuntimeError) as ei:
        clone.clone_repository(f"file://{tmp_path}/no-such-repo", str(dest))
    msg = str(ei.value)
    _assert_clean(msg, dest)
    assert "not found" in msg.lower() or "not accessible" in msg.lower(), msg
    assert not dest.exists()


def test_unknown_commit_says_the_commit_was_not_found(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.email=a@b", "-c", "user.name=n", *a],
                                    check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    (src / "a.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-qm", "i")
    dest = tmp_path / "checkout"
    with pytest.raises(RuntimeError) as ei:
        clone.clone_repository(f"file://{src}", str(dest), commit_sha="deadbeef" * 5)
    msg = str(ei.value)
    _assert_clean(msg, dest)
    assert "commit" in msg.lower(), msg
    assert not dest.exists()


def test_redirect_is_reported_as_a_redirect_and_not_followed(tmp_path):
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(301)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    dest = tmp_path / "d"
    try:
        with pytest.raises(RuntimeError) as ei:
            clone.clone_repository(f"http://127.0.0.1:{srv.server_address[1]}/o/r.git", str(dest))
    finally:
        srv.shutdown()
        srv.server_close()
    msg = str(ei.value)
    _assert_clean(msg, dest)
    assert "redirect" in msg.lower(), msg


def test_timeout_message_is_clear_and_clean(tmp_path, monkeypatch):
    def boom(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(clone.subprocess, "run", boom)
    dest = tmp_path / "d"
    with pytest.raises(RuntimeError) as ei:
        clone.clone_repository("https://github.com/o/r", str(dest))
    msg = str(ei.value)
    _assert_clean(msg, dest)
    assert "timed out" in msg.lower(), msg


def test_credentials_in_url_or_stderr_never_appear(tmp_path, monkeypatch):
    secret = "ghp_SECRETTOKEN123456"

    def fail(cmd, *a, **k):
        raise subprocess.CalledProcessError(
            128, cmd, stderr=f"fatal: Authentication failed for 'https://user:{secret}@github.com/o/r/'")

    monkeypatch.setattr(clone.subprocess, "run", fail)
    dest = tmp_path / "d"
    with pytest.raises(RuntimeError) as ei:
        clone.clone_repository(f"https://user:{secret}@github.com/o/r", str(dest))
    msg = str(ei.value)
    assert secret not in msg, msg
    _assert_clean(msg, dest)


def test_unexpected_error_does_not_leak_paths(tmp_path, monkeypatch):
    def fail(cmd, *a, **k):
        raise PermissionError(13, "Permission denied", "/srv/private/secret-dir")

    monkeypatch.setattr(clone.subprocess, "run", fail)
    with pytest.raises(RuntimeError) as ei:
        clone.clone_repository("https://github.com/o/r", str(tmp_path / "d"))
    msg = str(ei.value)
    assert "/srv/private" not in msg, msg
    assert "PermissionError" in msg


def test_size_limit_message_is_preserved(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    (src / "big.bin").write_bytes(b"x" * 2_000_000)
    subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.email=a@b", "-c", "user.name=n", "commit", "-qm", "i"], check=True)
    monkeypatch.setenv("REPO_MAX_MB", "1")
    dest = tmp_path / "d"
    with pytest.raises(RuntimeError, match="exceeds configured size limit") as ei:
        clone.clone_repository(f"file://{src}", str(dest))
    _assert_clean(str(ei.value), dest)
    assert not dest.exists()
