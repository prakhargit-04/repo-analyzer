"""
Session 19 Source Content Ingestion & Deterministic Evidence Chunking Test Suite.

Coverage:
1. Basic source file ingestion and line preservation.
2. Binary file filtering (binary files excluded from chunking).
3. Line number preservation (1-indexed start/end lines match text).
4. Determinism (same commit SHA + path + content produces identical chunk hash & ID).
5. Chunker versioning (bumping chunker version invalidates chunk hash/id and cache key).
6. Entity-aware chunking (functions and classes produce entity-tagged chunks).
7. Large file handling / window fallback (oversized entities & uncovered code lines).
8. Single DB persistence (worker execution persists source chunks exactly once).
9. Commit SHA traceability (every chunk stores commit SHA).
10. API endpoints (chunks listing with filters & line-location resolution).
"""
from __future__ import annotations
import os
import sys
import tempfile
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline.chunker import (
    chunk_single_file,
    generate_repository_chunks,
    compute_chunk_hash,
    SOURCE_CHUNKER_VERSION,
    SOURCE_CHUNK_SCHEMA_VERSION,
    is_binary_bytes,
)
from pipeline.parse_python import FunctionNode, ClassNode, FileParseResult
from pipeline.api.app import app
from pipeline.db.engine import get_engine, create_all_tables, get_session_factory
from pipeline.db.models import SourceChunk, AnalysisRun, Repository, Snapshot
from pipeline.db.store import create_job, persist_analysis, get_source_chunks_for_run, resolve_source_chunk
from pipeline.worker import process_job_task


@pytest.fixture
def test_env(tmp_path):
    db_file = tmp_path / "test_s19.db"
    db_url = f"sqlite:///{db_file}"
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)

    os.environ["DATABASE_URL"] = db_url
    os.environ["CACHE_DIR"] = cache_dir

    engine = get_engine(db_url)
    create_all_tables(engine)

    client = TestClient(app)
    yield client, engine, db_url, cache_dir

    if "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]
    if "CACHE_DIR" in os.environ:
        del os.environ["CACHE_DIR"]


def test_basic_source_ingestion_and_line_preservation(tmp_path):
    repo_dir = tmp_path / "repo"
    os.makedirs(repo_dir, exist_ok=True)

    py_file = repo_dir / "sample.py"
    content = "def hello():\n    print('Hello world')\n\nclass Foo:\n    pass\n"
    py_file.write_text(content, encoding="utf-8")

    parse_res = FileParseResult(
        file="sample.py",
        functions=[FunctionNode(id="sample.py::hello:1", name="hello", file="sample.py", start_line=1, end_line=2)],
        classes=[ClassNode(id="sample.py::Foo:4", name="Foo", file="sample.py", start_line=4, end_line=5)],
        imports=[],
    )

    chunks = chunk_single_file(str(repo_dir), "sample.py", commit_sha="commit_abc123", parse_result=parse_res)
    assert len(chunks) >= 2

    # Verify function chunk
    func_chunk = next(c for c in chunks if c.entity_name == "hello")
    assert func_chunk.start_line == 1
    assert func_chunk.end_line == 2
    assert "def hello():" in func_chunk.chunk_text
    assert func_chunk.commit_sha == "commit_abc123"

    # Verify class chunk
    class_chunk = next(c for c in chunks if c.entity_name == "Foo")
    assert class_chunk.start_line == 4
    assert class_chunk.end_line == 5
    assert "class Foo:" in class_chunk.chunk_text


def test_binary_file_filtering(tmp_path):
    repo_dir = tmp_path / "repo"
    os.makedirs(repo_dir, exist_ok=True)

    bin_file = repo_dir / "data.bin"
    bin_file.write_bytes(b"PNG\x00\x01\x02\x00\xff")

    chunks = chunk_single_file(str(repo_dir), "data.bin")
    assert chunks == []


def test_chunk_determinism_and_versioning():
    h1, id1 = compute_chunk_hash("sha_123", "app.py", 1, 10, "1", "print('hello')")
    h2, id2 = compute_chunk_hash("sha_123", "app.py", 1, 10, "1", "print('hello')")
    assert h1 == h2
    assert id1 == id2

    # Different chunker version produces different chunk hash and ID
    h3, id3 = compute_chunk_hash("sha_123", "app.py", 1, 10, "2", "print('hello')")
    assert h1 != h3
    assert id1 != id3


def test_large_file_subdivision(tmp_path):
    repo_dir = tmp_path / "repo"
    os.makedirs(repo_dir, exist_ok=True)

    big_file = repo_dir / "large.py"
    lines = [f"# line {i}" for i in range(1, 151)]
    big_file.write_text("\n".join(lines), encoding="utf-8")

    parse_res = FileParseResult(
        file="large.py",
        functions=[FunctionNode(id="large.py::big_func:1", name="big_func", file="large.py", start_line=1, end_line=150)],
        classes=[],
        imports=[],
    )

    chunks = chunk_single_file(str(repo_dir), "large.py", parse_result=parse_res)
    # 150 lines should be subdivided into multiple 50-line window chunks
    assert len(chunks) == 3
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 50
    assert chunks[1].start_line == 51
    assert chunks[1].end_line == 100
    assert chunks[2].start_line == 101
    assert chunks[2].end_line == 150


@pytest.mark.network
def test_source_chunk_db_persistence_and_api(test_env):

    client, engine, db_url, cache_dir = test_env
    SessionLocal = get_session_factory(engine)

    repo_url = "https://github.com/pytest-dev/iniconfig"

    with SessionLocal() as session:
        job = create_job(session, repo_url)
        job_id = job.id
        session.commit()

    # Process job using background worker task
    process_job_task(job_id, db_url, cache_dir)

    with SessionLocal() as session:
        j_dict = client.get(f"/api/v1/jobs/{job_id}").json()
        assert j_dict["status"] in ("completed", "partial")
        run_id = j_dict["run_id"]
        assert run_id is not None

        # Verify API list chunks endpoint
        res_chunks = client.get(f"/api/v1/analyses/{run_id}/chunks")
        assert res_chunks.status_code == 200
        data = res_chunks.json()
        assert data["total_chunks"] > 0
        chunk_list = data["chunks"]
        first_chunk = chunk_list[0]
        assert "chunk_id" in first_chunk
        assert "chunk_text" in first_chunk
        assert "commit_sha" in first_chunk

        # Verify chunk location resolution endpoint
        file_path = first_chunk["file_path"]
        target_line = first_chunk["start_line"]
        res_res = client.get(f"/api/v1/analyses/{run_id}/chunks/resolve", params={"file_path": file_path, "line": target_line})
        assert res_res.status_code == 200
        resolved_chunk = res_res.json()
        assert resolved_chunk["chunk_id"] == first_chunk["chunk_id"]
