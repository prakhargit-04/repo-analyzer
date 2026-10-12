"""
v0.24.5 hardening tests: clone hardening, health-score formula_version,
commit A -> commit B cache invalidation. Written before the fixes.
"""
from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import clone
import static_analysis
from main import run_pipeline


def _git(cwd, *args, env_extra=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.x"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture
def three_commit_repo(tmp_path):
    repo = tmp_path / "src_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    for i in range(3):
        (repo / "a.py").write_text(f"def f{i}():\n    return {i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    return repo, shas


# ------------------------------------------------------------ clone hardening
class _Capture:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((list(cmd), kw))

        class R:
            returncode = 0
            stdout = "a" * 40 + "\n"
            stderr = ""
        return R()


def test_clone_command_is_hardened(monkeypatch, tmp_path):
    cap = _Capture()
    monkeypatch.setattr(clone.subprocess, "run", cap)
    clone.clone_repository("https://github.com/o/r", str(tmp_path / "d"))
    cmd, kw = cap.calls[0]
    assert cmd[0] == "git" and cmd[cmd.index("clone") - 1] != "--"
    joined = " ".join(cmd)
    for needed in ("core.hooksPath=/dev/null", "protocol.ext.allow=never",
                   "http.followRedirects=false", "submodule.recurse=false"):
        assert needed in joined, needed
    assert "--depth" in cmd and cmd[cmd.index("--depth") + 1] == "1"
    assert "--no-recurse-submodules" in cmd
    assert cmd.index("--") < cmd.index("https://github.com/o/r")  # url after option terminator
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert kw["env"].get("GIT_ASKPASS") is not None  # never prompt for credentials


def test_pinned_sha_clone_keeps_history_needed_for_checkout(monkeypatch, tmp_path):
    cap = _Capture()
    monkeypatch.setattr(clone.subprocess, "run", cap)
    clone.clone_repository("https://github.com/o/r", str(tmp_path / "d"), commit_sha="abcdef1")
    clone_cmd = cap.calls[0][0]
    assert "--depth" not in clone_cmd  # a specific SHA may not be on the tip of a shallow clone
    assert "http.followRedirects=false" in " ".join(clone_cmd)
    assert "http.followRedirects=false" in " ".join(cap.calls[1][0])  # checkout call also hardened


def test_ls_remote_is_hardened_too(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(clone.subprocess, "run", cap)
    clone.resolve_remote_sha("https://github.com/o/r")
    cmd, kw = cap.calls[0]
    assert "http.followRedirects=false" in " ".join(cmd)
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_clone_is_really_shallow_without_sha(three_commit_repo, tmp_path):
    repo, shas = three_commit_repo
    dest = tmp_path / "dest"
    resolved = clone.clone_repository(f"file://{repo}", str(dest))
    assert resolved == shas[-1]
    assert _git(dest, "rev-list", "--count", "HEAD") == "1"


def test_clone_with_sha_checks_out_that_commit(three_commit_repo, tmp_path):
    repo, shas = three_commit_repo
    dest = tmp_path / "dest"
    assert clone.clone_repository(f"file://{repo}", str(dest), commit_sha=shas[0]) == shas[0]


def test_submodules_are_not_fetched(three_commit_repo, tmp_path):
    repo, _ = three_commit_repo
    sub = tmp_path / "sub_repo"
    sub.mkdir()
    _git(sub, "init", "-q", "-b", "main")
    (sub / "s.py").write_text("x = 1\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "s")
    _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", f"file://{sub}", "vendor/sub")
    _git(repo, "commit", "-q", "-m", "add submodule")
    dest = tmp_path / "dest"
    clone.clone_repository(f"file://{repo}", str(dest))
    assert not (dest / "vendor" / "sub" / "s.py").exists()
    assert not (dest / ".git" / "modules").exists()


class _Hits(http.server.BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


def _redirector(target_port):
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(301)
            self.send_header("Location", f"http://127.0.0.1:{target_port}{self.path}")
            self.end_headers()

        def log_message(self, *a):
            pass
    return Redirect


def test_redirect_to_another_host_is_rejected_and_never_followed(tmp_path):
    _Hits.hits = 0
    target = http.server.HTTPServer(("127.0.0.1", 0), _Hits)
    front = http.server.HTTPServer(("127.0.0.1", 0), _redirector(target.server_address[1]))
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (target, front)]
    for t in threads:
        t.start()
    try:
        with pytest.raises(RuntimeError, match="Failed to clone"):
            clone.clone_repository(f"http://127.0.0.1:{front.server_address[1]}/o/r.git", str(tmp_path / "d"))
        assert _Hits.hits == 0, "git followed a redirect to a different host"
        assert not (tmp_path / "d").exists()
    finally:
        for s in (target, front):
            s.shutdown()
            s.server_close()


# ----------------------------------------------------- health formula_version
def _ok():
    return {"status": "success", "results": []}


def test_health_score_carries_formula_version_in_every_shape():
    from health_score import compute_health_score, HEALTH_FORMULA_VERSION
    full = compute_health_score({"complexity": _ok(), "maintainability": _ok(), "security": _ok(),
                                 "semgrep_findings": _ok(), "gitleaks_findings": _ok(), "osv_vulnerabilities": _ok()})
    reduced = compute_health_score({"complexity": _ok(), "maintainability": _ok(), "security": _ok(),
                                    "semgrep_findings": {"status": "unavailable"}, "gitleaks_findings": _ok(),
                                    "osv_vulnerabilities": _ok()})
    empty = compute_health_score({"complexity": {"status": "unavailable"}, "maintainability": {"status": "unavailable"},
                                  "security": {"status": "unavailable"}})
    for hs in (full, reduced, empty):
        assert hs["formula_version"] == HEALTH_FORMULA_VERSION
    assert isinstance(HEALTH_FORMULA_VERSION, str) and HEALTH_FORMULA_VERSION


def test_formula_version_documented_in_schema():
    from health_score import HEALTH_FORMULA_VERSION
    text = (ROOT / "SCHEMA.md").read_text(encoding="utf-8")
    assert "formula_version" in text and HEALTH_FORMULA_VERSION in text


@pytest.fixture
def db_client(tmp_path, monkeypatch):
    from db.engine import get_engine, create_all_tables, get_session_factory
    from api.app import app
    db_url = f"sqlite:///{tmp_path / 'f.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(static_analysis, "_SEMGREP_BINARY", None)
    engine = get_engine(db_url)
    create_all_tables(engine)
    with TestClient(app) as client:
        yield client, get_session_factory(engine), engine
    engine.dispose()


def test_formula_version_is_persisted_and_returned_by_api(db_client, tmp_path):
    from db.store import persist_analysis
    from health_score import HEALTH_FORMULA_VERSION
    client, Session, _ = db_client
    result = run_pipeline(None, str(ROOT / "tests" / "fixtures" / "success_repo"), None, str(tmp_path / "c"))
    with Session() as s:
        run_id = persist_analysis(s, result)
        s.commit()
    hs = client.get(f"/api/v1/analyses/{run_id}/summary").json()["health_score"]
    assert hs["formula_version"] == HEALTH_FORMULA_VERSION
    assert client.get(f"/api/v1/analyses/{run_id}").json()["health_score"]["formula_version"] == HEALTH_FORMULA_VERSION


def test_legacy_row_without_formula_version_is_not_given_a_made_up_one(db_client, tmp_path):
    from db.store import persist_analysis
    from db.models import HealthScore
    client, Session, _ = db_client
    result = run_pipeline(None, str(ROOT / "tests" / "fixtures" / "success_repo"), None, str(tmp_path / "c"))
    with Session() as s:
        run_id = persist_analysis(s, result)
        s.query(HealthScore).update({"formula_version": None})
        s.commit()
    assert client.get(f"/api/v1/analyses/{run_id}/summary").json()["health_score"].get("formula_version") is None


def test_pre_existing_database_gets_formula_version_column(tmp_path):
    from sqlalchemy import inspect, text
    from db.engine import get_engine, create_all_tables
    from db.models import Base
    engine = get_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE health_scores DROP COLUMN formula_version"))
    create_all_tables(engine)
    assert "formula_version" in {c["name"] for c in inspect(engine).get_columns("health_scores")}
    engine.dispose()


def test_alembic_0007_chains_from_0006():
    src = (ROOT / "pipeline" / "db" / "migrations" / "versions" / "0007_health_formula_version.py").read_text(encoding="utf-8")
    assert 'down_revision = "0006"' in src and "formula_version" in src


# ------------------------------------------- commit A -> commit B cache behaviour
@pytest.fixture
def local_git_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(static_analysis, "_SEMGREP_BINARY", None)  # cache logic does not depend on Semgrep
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("def alpha():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    return repo


def _run(repo, cache, events=None):
    cb = (lambda s, st, d: events.append((s, st, d))) if events is not None else None
    return run_pipeline(None, str(repo), None, str(cache), stage_callback=cb)


def _hit(events):
    return any("file cache" in (d or "").lower() for s, _, d in events if s == "embedding")


def _names(res):
    return {n.get("name") for n in res["knowledge_graph"]["nodes"] if n.get("type") == "function"}


def test_commit_a_then_b_never_reuses_stale_results(local_git_repo, tmp_path):
    repo, cache = local_git_repo, tmp_path / "cache"
    ev1, ev2, ev3 = [], [], []
    a1 = _run(repo, cache, ev1)
    assert not _hit(ev1) and _names(a1) == {"alpha"}
    a2 = _run(repo, cache, ev2)
    assert _hit(ev2), "identical content must be a cache hit"
    assert a2["cache_snapshot_id"] == a1["cache_snapshot_id"]

    (repo / "a.py").write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return eval('2')\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B")
    b = _run(repo, cache, ev3)
    assert not _hit(ev3), "changed content must NOT be served from the cache"
    assert _names(b) == {"alpha", "beta"}
    assert b["cache_snapshot_id"] != a1["cache_snapshot_id"]
    chunk_text = " ".join(c["chunk_text"] for c in b["source_chunks"])
    assert "beta" in chunk_text
    assert {c["chunk_id"] for c in b["source_embeddings"]} == {c["chunk_id"] for c in b["source_chunks"]}

    # going back to A's exact content hits A's entry, with none of B's data
    _git(repo, "checkout", "-q", "HEAD~1", "--", "a.py")
    ev4 = []
    back = _run(repo, cache, ev4)
    assert _hit(ev4) and _names(back) == {"alpha"}


def test_analyzer_or_embedding_change_invalidates_cache(local_git_repo, tmp_path, monkeypatch):
    import util
    repo, cache = local_git_repo, tmp_path / "cache"
    _run(repo, cache)
    ev = []
    _run(repo, cache, ev)
    assert _hit(ev)

    monkeypatch.setattr(util, "ANALYZER_VERSION", "9.9.9-test")
    ev = []
    _run(repo, cache, ev)
    assert not _hit(ev), "analyzer version change must invalidate"
    monkeypatch.undo()

    monkeypatch.setattr(static_analysis, "_SEMGREP_BINARY", None)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "test")
    monkeypatch.setattr("embeddings.embedding_cache_identity",
                        lambda provider_name=None: ("test-deterministic", "another-model", "1.0"))
    ev = []
    _run(repo, cache, ev)
    assert not _hit(ev), "embedding model change must invalidate"
