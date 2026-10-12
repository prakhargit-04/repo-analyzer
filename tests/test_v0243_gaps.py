"""
v0.24.3 regression tests for gaps found when auditing v0.24.2.
Written BEFORE the fixes; each fails against 0.24.2 (see REPORT.md).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import static_analysis
from main import run_pipeline, load_cache
from db.engine import get_engine, create_all_tables, get_session_factory
from db.store import persist_analysis
from api.app import app

FIXTURES = ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------- 1. cache key
def test_cache_key_changes_with_embedding_model_name(monkeypatch):
    import util
    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "model-a")
    k_a = util.build_cache_key("snap")
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", "model-b")
    k_b = util.build_cache_key("snap")
    assert k_a != k_b


def test_cache_key_rejects_unknown_provider_and_never_instantiates(monkeypatch):
    import util, embeddings
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nonsense")
    with pytest.raises(ValueError):
        util.build_cache_key("snap")

    def boom(*a, **k):
        raise AssertionError("provider instantiated")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "test")
    monkeypatch.setattr(embeddings, "get_embedding_provider", boom)
    monkeypatch.setattr(embeddings.SentenceTransformerProvider, "__init__", boom)
    assert util.build_cache_key("snap")


# ------------------------------------------------------- 2. compact cache file
@pytest.fixture
def no_semgrep(monkeypatch):
    monkeypatch.setattr(static_analysis, "_SEMGREP_BINARY", None)


def _cache_file(cache_dir):
    files = [p for p in Path(cache_dir).glob("*.json")]
    assert len(files) == 1
    return files[0]


def test_cache_file_stores_vectors_compactly_and_losslessly(tmp_path, no_semgrep):
    repo = str(FIXTURES / "success_repo")
    fresh = run_pipeline(None, repo, None, str(tmp_path))
    assert fresh["source_embeddings"], "fixture must produce embeddings"
    path = _cache_file(tmp_path)
    raw = path.read_text(encoding="utf-8")
    on_disk = json.loads(raw)
    emb = on_disk["source_embeddings"][0]
    assert "vector" not in emb and "vector_b64" in emb, "vectors must be stored compactly, not as float lists"
    # Compare the embeddings section only: same indent, plain float lists vs packed.
    naive = json.dumps(fresh["source_embeddings"], indent=2, sort_keys=True)
    packed = json.dumps(on_disk["source_embeddings"], indent=2, sort_keys=True)
    assert len(packed) < 0.5 * len(naive), (len(packed), len(naive))

    cached = run_pipeline(None, repo, None, str(tmp_path))
    # Vectors are stored as float32; round-trip introduces at most ~1e-7 relative
    # error — well within the precision of any embedding model output.
    for fresh_emb, cached_emb in zip(fresh["source_embeddings"], cached["source_embeddings"]):
        for a, b in zip(fresh_emb["vector"], cached_emb["vector"]):
            assert abs(a - b) < 1e-6, f"vector element drift too large: {a!r} vs {b!r}"


def test_load_cache_still_accepts_legacy_list_vectors(tmp_path):
    legacy = {"schema_version": "1.0.0", "knowledge_graph": {"nodes": [], "edges": []},
              "source_embeddings": [{"chunk_id": "c", "vector": [0.25, -0.5]}]}
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    assert load_cache(str(p))["source_embeddings"][0]["vector"] == [0.25, -0.5]


def test_cache_schema_version_bumped_for_format_change():
    import util
    assert util.CACHE_SCHEMA_VERSION == "v6"
    assert "v6" in (ROOT / "SCHEMA.md").read_text(encoding="utf-8")


# ------------------------------------------- 3. reduced component set is stated
def _ok(results=None):
    return {"status": "success", "results": results or []}


def test_health_score_states_reduced_component_set():
    from health_score import compute_health_score
    full = compute_health_score({
        "complexity": _ok(), "maintainability": _ok(), "security": _ok(),
        "semgrep_findings": _ok(), "gitleaks_findings": _ok(), "osv_vulnerabilities": _ok(),
    })
    assert full["reduced_component_set"] is False
    assert "reduced" not in full["note"].lower()

    reduced = compute_health_score({
        "complexity": _ok(), "maintainability": _ok(), "security": _ok(),
        "semgrep_findings": {"status": "unavailable"}, "gitleaks_findings": _ok(),
        "osv_vulnerabilities": {"status": "failed"},
    })
    assert reduced["reduced_component_set"] is True
    assert reduced["components_scored"] == ["complexity", "maintainability", "security", "secrets"]
    assert "4 of 6" in reduced["note"] and "sast" in reduced["note"]
    assert reduced["status"] == "partial"


# ------------------------------------- 4. existence checks must not rebuild all
@pytest.fixture
def api(tmp_path, monkeypatch, no_semgrep):
    db_url = f"sqlite:///{tmp_path / 'gaps.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    engine = get_engine(db_url)
    create_all_tables(engine)
    SessionLocal = get_session_factory(engine)
    result = run_pipeline(None, str(FIXTURES / "success_repo"), None, str(tmp_path / "c2"))
    with SessionLocal() as s:
        run_id = persist_analysis(s, result)
        s.commit()
    with TestClient(app) as client:
        yield client, run_id, result
    engine.dispose()


def _forbid_full_rebuild(monkeypatch):
    import db.store as store
    import api.routes as routes
    import rag.service as service

    def boom(*a, **k):
        raise AssertionError("full analysis rebuilt for a cheap endpoint")
    monkeypatch.setattr(store, "_run_to_dict", boom)
    for mod in (routes, service):
        if hasattr(mod, "get_analysis_by_run_id"):
            monkeypatch.setattr(mod, "get_analysis_by_run_id", boom)


def test_cheap_endpoints_do_not_rebuild_full_analysis(api, monkeypatch):
    client, run_id, result = api
    expected_files = [n["id"] for n in result["knowledge_graph"]["nodes"] if n.get("type") == "file"]
    full_status = client.get(f"/api/v1/analyses/{run_id}/status").json()
    expected_entities = client.get(f"/api/v1/analyses/{run_id}/files/{expected_files[0]}").json()
    _forbid_full_rebuild(monkeypatch)

    assert client.get(f"/api/v1/analyses/{run_id}/status").json() == full_status
    detail = client.get(f"/api/v1/analyses/{run_id}/files/{expected_files[0]}")
    assert detail.status_code == 200
    assert sorted(e["id"] for e in detail.json()["entities"]) == sorted(e["id"] for e in expected_entities["entities"])
    assert client.get(f"/api/v1/analyses/{run_id}/chunks").status_code == 200
    assert client.post(f"/api/v1/analyses/{run_id}/retrieve", json={"query": "x", "top_k": 2}).status_code == 200
    assert client.get(f"/api/v1/analyses/{run_id}/retrieve", params={"query": "x"}).status_code == 200
    assert client.post(f"/api/v1/analyses/{run_id}/ask", json={"question": "what is app?"}).status_code == 200


def test_cheap_endpoints_still_404_for_unknown_run(api, monkeypatch):
    client, _, _ = api
    _forbid_full_rebuild(monkeypatch)
    for method, url, kw in (
        ("get", "/api/v1/analyses/nope/status", {}),
        ("get", "/api/v1/analyses/nope/files/a.py", {}),
        ("get", "/api/v1/analyses/nope/chunks", {}),
        ("post", "/api/v1/analyses/nope/retrieve", {"json": {"query": "x"}}),
        ("post", "/api/v1/analyses/nope/ask", {"json": {"question": "x"}}),
    ):
        assert getattr(client, method)(url, **kw).status_code == 404, url


# ------------------------------------------------------------ 5. stale docstring
def test_main_docstring_no_longer_claims_python_only():
    text = (ROOT / "pipeline" / "main.py").read_text(encoding="utf-8")
    assert "Python-only" not in text and "Tier 1" not in text
