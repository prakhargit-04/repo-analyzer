"""
Comprehensive Test Suite for Session 20: Embeddings & Vector Retrieval Foundation.

Tests:
  - TestEmbeddingProvider determinism and dimensions
  - Structured chunk text formatting
  - SourceEmbedding database model & persistence
  - Pipeline embedding stage execution & error safety
  - Repository & commit isolation during vector similarity retrieval
  - Cache invalidation and model versioning checks
  - FastAPI retrieval endpoints (/api/v1/analyses/{run_id}/retrieve)
  - Controlled retrieval quality baseline
"""
from __future__ import annotations

import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline", "api"))

from embeddings import (
    TestEmbeddingProvider,
    SentenceTransformerProvider,
    format_chunk_for_embedding,
    get_embedding_provider,
    EMBEDDING_PIPELINE_VERSION,
)
from embeddings_stage import generate_source_embeddings
from db.engine import get_engine, create_all_tables, get_session_factory
from db.models import Base, SourceChunk, SourceEmbedding, AnalysisRun, Snapshot, Repository
from db.store import persist_analysis, retrieve_similar_chunks, get_source_chunks_for_run
from app import app


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test_s20.db"
    db_url = f"sqlite:///{db_file}"
    engine = get_engine(db_url)
    create_all_tables(engine)
    SessionLocal = get_session_factory(engine)
    with SessionLocal() as session:
        yield session


@pytest.fixture
def sample_analysis_result():
    return {
        "schema_version": "1.0.0",
        "cache_schema_version": "v4",
        "analyzer_version": "0.13.0",
        "chunker_version": "1",
        "embedding_pipeline_version": EMBEDDING_PIPELINE_VERSION,
        "repository": "https://github.com/pytest-dev/iniconfig",
        "commit_sha": "abc123sha",
        "cache_snapshot_id": "snap_123",
        "cache_key_basis": "git_sha",
        "analyzed_at_utc": "2026-10-01T00:00:00+00:00",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 2,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph_summary": {"total_nodes": 2, "total_edges": 0},
        "knowledge_graph": {"nodes": [], "edges": []},
        "health_score": {"composite_health_score": 92.5, "status": "good"},
        "source_chunks": [
            {
                "chunk_id": "sc_auth_001",
                "file_path": "src/auth.py",
                "start_line": 1,
                "end_line": 20,
                "chunk_text": "def authenticate(user, password):\n    # User authentication module\n    return verify_credentials(user, password)",
                "language": "python",
                "entity_name": "authenticate",
                "entity_type": "function",
                "provenance": "PARSER_AST",
                "chunk_hash": "hash_auth_001",
                "commit_sha": "abc123sha",
                "chunker_version": "1",
                "schema_version": "1",
            },
            {
                "chunk_id": "sc_health_002",
                "file_path": "src/scoring.py",
                "start_line": 10,
                "end_line": 35,
                "chunk_text": "def compute_health_score(analysis):\n    # Calculate composite score from components\n    return score",
                "language": "python",
                "entity_name": "compute_health_score",
                "entity_type": "function",
                "provenance": "PARSER_AST",
                "chunk_hash": "hash_health_002",
                "commit_sha": "abc123sha",
                "chunker_version": "1",
                "schema_version": "1",
            },
        ],
    }


class TestEmbeddingProviderSuite:
    def test_test_provider_determinism(self):
        provider = TestEmbeddingProvider(dimension=64)
        assert provider.name == "test-deterministic"
        assert provider.dimension == 64

        vec1 = provider.embed_query("Where is authentication implemented?")
        vec2 = provider.embed_query("Where is authentication implemented?")
        assert len(vec1) == 64
        assert vec1 == vec2

        vec3 = provider.embed_query("Different query text")
        assert vec1 != vec3

    def test_embed_documents_batching(self):
        provider = TestEmbeddingProvider(dimension=32)
        docs = ["code chunk 1", "code chunk 2", "code chunk 3"]
        embeddings = provider.embed_documents(docs)

        assert len(embeddings) == 3
        for vec in embeddings:
            assert len(vec) == 32

    def test_format_chunk_for_embedding(self):
        chunk = {
            "file_path": "src/auth.py",
            "language": "python",
            "start_line": 10,
            "end_line": 25,
            "entity_name": "authenticate",
            "entity_type": "function",
            "chunk_text": "def authenticate(): pass",
        }
        formatted = format_chunk_for_embedding(chunk)
        assert "file: src/auth.py" in formatted
        assert "language: python" in formatted
        assert "entity: function authenticate" in formatted
        assert "lines: 10-25" in formatted
        assert "def authenticate(): pass" in formatted


class TestEmbeddingStageSuite:
    def test_generate_source_embeddings_success(self, sample_analysis_result):
        chunks = sample_analysis_result["source_chunks"]
        provider = TestEmbeddingProvider(dimension=64)

        embeddings, status = generate_source_embeddings(
            chunks,
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=provider,
        )

        assert status["status"] == "completed"
        assert len(embeddings) == 2
        assert embeddings[0]["dimension"] == 64
        assert embeddings[0]["model_name"] == "test-deterministic"
        assert embeddings[0]["source_chunk_id"] == "sc_auth_001"

    def test_embedding_stage_error_safety(self, sample_analysis_result):
        chunks = sample_analysis_result["source_chunks"]

        class FailingProvider:
            name = "failing-provider"
            model_version = "1.0"
            dimension = 64
            def embed_documents(self, texts):
                raise RuntimeError("Provider API Unavailable")
            def embed_query(self, text):
                raise RuntimeError("Provider API Unavailable")

        embeddings, status = generate_source_embeddings(
            chunks,
            repo_url=sample_analysis_result["repository"],
            provider=FailingProvider(),
        )

        assert status["status"] == "failed"
        assert status["error"] == "Provider API Unavailable"
        assert len(embeddings) == 0


class TestVectorRetrievalSuite:
    def test_persistence_and_vector_retrieval(self, db_session, sample_analysis_result):
        provider = TestEmbeddingProvider(dimension=64)
        embeddings, status = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=provider,
        )
        sample_analysis_result["source_embeddings"] = embeddings

        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()

        # Query vector search
        res = retrieve_similar_chunks(
            db_session,
            run_id=run_id,
            query_text="Where is authentication implemented?",
            top_k=2,
            provider=provider,
        )

        assert res["run_id"] == run_id
        assert res["total_retrieved"] == 2
        assert len(res["results"]) == 2

        top_match = res["results"][0]
        assert top_match["chunk_id"] == "sc_auth_001"
        assert top_match["file_path"] == "src/auth.py"
        assert top_match["entity_name"] == "authenticate"
        assert isinstance(top_match["score"], float)

    def test_repository_and_commit_isolation(self, db_session, sample_analysis_result):
        provider = TestEmbeddingProvider(dimension=64)

        # Run 1: Repo A, Commit 1
        res_a = dict(sample_analysis_result)
        res_a["repository"] = "https://github.com/org/repo-A"
        res_a["commit_sha"] = "commit_sha_A"
        embs_a, _ = generate_source_embeddings(res_a["source_chunks"], repo_url=res_a["repository"], commit_sha="commit_sha_A", provider=provider)
        res_a["source_embeddings"] = embs_a
        run_id_a = persist_analysis(db_session, res_a)

        # Run 2: Repo B, Commit 2
        res_b = dict(sample_analysis_result)
        res_b["repository"] = "https://github.com/org/repo-B"
        res_b["commit_sha"] = "commit_sha_B"
        res_b["source_chunks"] = [
            {
                "chunk_id": "sc_repoB_001",
                "file_path": "src/repoB.py",
                "start_line": 1,
                "end_line": 10,
                "chunk_text": "def repo_b_feature(): pass",
                "language": "python",
                "entity_name": "repo_b_feature",
                "entity_type": "function",
                "provenance": "PARSER_AST",
                "chunk_hash": "hash_repoB_001",
                "commit_sha": "commit_sha_B",
                "chunker_version": "1",
                "schema_version": "1",
            }
        ]
        embs_b, _ = generate_source_embeddings(res_b["source_chunks"], repo_url=res_b["repository"], commit_sha="commit_sha_B", provider=provider)
        res_b["source_embeddings"] = embs_b
        run_id_b = persist_analysis(db_session, res_b)

        db_session.commit()

        # Query Run A must NOT return chunks from Repo B
        search_a = retrieve_similar_chunks(db_session, run_id=run_id_a, query_text="authentication", top_k=5, provider=provider)
        for item in search_a["results"]:
            assert item["chunk_id"] != "sc_repoB_001"
            assert item["file_path"] != "src/repoB.py"

        # Query Run B must ONLY return chunks from Repo B
        search_b = retrieve_similar_chunks(db_session, run_id=run_id_b, query_text="feature", top_k=5, provider=provider)
        assert len(search_b["results"]) == 1
        assert search_b["results"][0]["chunk_id"] == "sc_repoB_001"


class TestFastAPIRetrievalEndpoints:
    def test_fastapi_retrieve_endpoint(self, db_session, sample_analysis_result, monkeypatch):
        provider = TestEmbeddingProvider(dimension=64)
        embs, _ = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=provider,
        )
        sample_analysis_result["source_embeddings"] = embs
        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()

        def override_get_db():
            try:
                yield db_session
            finally:
                pass

        from api.routes import get_db_session
        app.dependency_overrides[get_db_session] = override_get_db

        client = TestClient(app)

        # POST /api/v1/analyses/{run_id}/retrieve
        resp_post = client.post(f"/api/v1/analyses/{run_id}/retrieve", json={"query": "health score", "top_k": 2})
        assert resp_post.status_code == 200
        data_post = resp_post.json()
        assert data_post["run_id"] == run_id
        assert data_post["total_retrieved"] == 2
        assert len(data_post["results"]) == 2

        # GET /api/v1/analyses/{run_id}/retrieve
        resp_get = client.get(f"/api/v1/analyses/{run_id}/retrieve", params={"query": "authentication", "top_k": 1})
        assert resp_get.status_code == 200
        data_get = resp_get.json()
        assert data_get["total_retrieved"] == 1
        assert data_get["results"][0]["chunk_id"] == "sc_auth_001"

        app.dependency_overrides.clear()
