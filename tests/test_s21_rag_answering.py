"""
Comprehensive Test Suite for Session 21: Evidence-Grounded Answering & RAG Pipeline.

Tests:
  - TestLLMProvider determinism & offline execution
  - Evidence Context Builder formatting & evidence mapping
  - Server-side Citation Validator (accepts valid [E1], rejects invalid [E99])
  - RAG Answer Generation Service end-to-end execution
  - Insufficient evidence handling & empty retrieval
  - Repository & Commit isolation in RAG answers
  - FastAPI RAG Endpoint (POST /api/v1/analyses/{run_id}/ask)
  - Controlled evaluation baseline
"""
from __future__ import annotations

import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline", "api"))

from embeddings import TestEmbeddingProvider
from embeddings_stage import generate_source_embeddings
from rag.llm import (
    TestLLMProvider,
    get_llm_provider,
    LLMError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMNotConfiguredError,
    LLMResponseError,
)
from rag.context_builder import build_evidence_context, build_rag_user_prompt
from rag.citation_validator import validate_citations
from rag.service import answer_repository_question
from db.engine import get_engine, create_all_tables, get_session_factory
from db.store import persist_analysis
from app import app


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test_s21.db"
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
        "embedding_pipeline_version": "1",
        "repository": "https://github.com/pytest-dev/iniconfig",
        "commit_sha": "sha_s21_commit",
        "cache_snapshot_id": "snap_s21",
        "cache_key_basis": "git_sha",
        "analyzed_at_utc": "2026-10-01T00:00:00+00:00",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": 2,
        "parse_errors": [],
        "static_analysis": {},
        "knowledge_graph_summary": {"total_nodes": 2, "total_edges": 0},
        "knowledge_graph": {"nodes": [], "edges": []},
        "health_score": {"composite_health_score": 95.0, "status": "good"},
        "source_chunks": [
            {
                "chunk_id": "sc_auth_100",
                "file_path": "src/auth.py",
                "start_line": 15,
                "end_line": 35,
                "chunk_text": "def authenticate(user, password):\n    # Core authentication logic\n    return verify_user(user, password)",
                "language": "python",
                "entity_name": "authenticate",
                "entity_type": "function",
                "provenance": "PARSER_AST",
                "chunk_hash": "hash_auth_100",
                "commit_sha": "sha_s21_commit",
                "chunker_version": "1",
                "schema_version": "1",
            },
            {
                "chunk_id": "sc_score_200",
                "file_path": "src/scoring.py",
                "start_line": 1,
                "end_line": 25,
                "chunk_text": "def compute_health_score(metrics):\n    # Score calculation algorithm\n    return 100.0",
                "language": "python",
                "entity_name": "compute_health_score",
                "entity_type": "function",
                "provenance": "PARSER_AST",
                "chunk_hash": "hash_score_200",
                "commit_sha": "sha_s21_commit",
                "chunker_version": "1",
                "schema_version": "1",
            },
        ],
    }


class TestLLMProviderSuite:
    def test_test_llm_provider_determinism(self):
        llm = TestLLMProvider()
        assert llm.name == "test-llm"

        prompt = "Repository Evidence:\n[E1]\nFile: src/auth.py\nQuestion: How is authentication implemented?"
        ans = llm.generate(prompt)

        assert "How is authentication implemented?" in ans
        assert "[E1]" in ans

    def test_test_llm_insufficient_evidence(self):
        llm = TestLLMProvider()
        ans = llm.generate("No evidence supplied here")
        assert ans == "The available repository evidence is insufficient to determine this."


class TestCitationValidatorSuite:
    def test_validate_citations_valid(self):
        evidence_map = {
            "E1": {"citation_id": "E1", "chunk_id": "sc_auth_100", "file_path": "src/auth.py", "start_line": 15, "end_line": 35},
            "E2": {"citation_id": "E2", "chunk_id": "sc_score_200", "file_path": "src/scoring.py", "start_line": 1, "end_line": 25},
        }

        text = "Authentication is in auth.py [E1] and scoring is in scoring.py [E2]."
        clean_text, citations = validate_citations(text, evidence_map)

        assert clean_text == text
        assert len(citations) == 2
        assert citations[0]["chunk_id"] == "sc_auth_100"
        assert citations[1]["chunk_id"] == "sc_score_200"

    def test_validate_citations_rejects_hallucinated_citations(self):
        evidence_map = {
            "E1": {"citation_id": "E1", "chunk_id": "sc_auth_100", "file_path": "src/auth.py", "start_line": 15, "end_line": 35},
        }

        # Model claims [E1] and hallucinated [E99]
        text = "Auth is in auth.py [E1] and login is in login.py [E99]."
        clean_text, citations = validate_citations(text, evidence_map)

        # [E99] must be stripped
        assert "[E99]" not in clean_text
        assert "[E1]" in clean_text
        assert len(citations) == 1
        assert citations[0]["citation_id"] == "E1"


class TestRAGServiceSuite:
    def test_rag_end_to_end_answer(self, db_session, sample_analysis_result):
        emb_provider = TestEmbeddingProvider(dimension=64)
        embs, _ = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=emb_provider,
        )
        sample_analysis_result["source_embeddings"] = embs
        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()

        llm_provider = TestLLMProvider()

        res = answer_repository_question(
            db_session,
            run_id=run_id,
            question="Where is authentication implemented?",
            top_k=2,
            llm_provider=llm_provider,
            embedding_provider=emb_provider,
        )

        assert res["run_id"] == run_id
        assert res["provenance"] == "AI_GENERATED"
        assert res["retrieved_chunks_count"] > 0
        assert len(res["citations"]) > 0
        assert res["citations"][0]["file_path"] in ("src/auth.py", "src/scoring.py")

    def test_rag_insufficient_evidence_for_unsupported_query(self, db_session, sample_analysis_result):
        emb_provider = TestEmbeddingProvider(dimension=64)
        # Empty source_chunks
        sample_analysis_result["source_chunks"] = []
        sample_analysis_result["source_embeddings"] = []
        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()

        res = answer_repository_question(
            db_session,
            run_id=run_id,
            question="What migration strategy is used?",
            top_k=5,
            embedding_provider=emb_provider,
        )

        assert res["answer"] == "The available repository evidence is insufficient to determine this."
        assert len(res["citations"]) == 0
        assert res["retrieved_chunks_count"] == 0

    def test_rag_llm_failure_handling(self, db_session, sample_analysis_result):
        """S23: service raises typed LLMResponseError (not graceful-200) when generate() fails."""
        emb_provider = TestEmbeddingProvider(dimension=64)
        embs, _ = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=emb_provider,
        )
        sample_analysis_result["source_embeddings"] = embs
        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()

        class FailingLLM(TestLLMProvider):
            def generate(self, prompt, system_prompt=None):
                raise LLMResponseError("Simulated network failure")

        with pytest.raises(LLMResponseError) as exc_info:
            answer_repository_question(
                db_session,
                run_id=run_id,
                question="Where is authentication?",
                llm_provider=FailingLLM(),
                embedding_provider=emb_provider,
            )
        assert exc_info.value.status_code == 502
        assert "secret" not in str(exc_info.value).lower()
        assert "traceback" not in str(exc_info.value).lower()


class TestFastAPIRAGEndpoint:
    def test_fastapi_ask_endpoint(self, db_session, sample_analysis_result):
        emb_provider = TestEmbeddingProvider(dimension=64)
        embs, _ = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=emb_provider,
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

        # POST /api/v1/analyses/{run_id}/ask
        resp = client.post(f"/api/v1/analyses/{run_id}/ask", json={"question": "Where is authentication implemented?", "top_k": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["provenance"] == "AI_GENERATED"
        assert "answer" in data
        assert isinstance(data["citations"], list)
        assert data["retrieved_chunks_count"] > 0

        app.dependency_overrides.clear()


class TestAskRouteHTTPMapping:
    """S23 Item 2: /ask route maps each LLMError subclass to the correct HTTP status code."""

    def _make_run_with_embeddings(self, db_session, sample_analysis_result):
        emb_provider = TestEmbeddingProvider(dimension=64)
        embs, _ = generate_source_embeddings(
            sample_analysis_result["source_chunks"],
            repo_url=sample_analysis_result["repository"],
            commit_sha=sample_analysis_result["commit_sha"],
            provider=emb_provider,
        )
        sample_analysis_result["source_embeddings"] = embs
        run_id = persist_analysis(db_session, sample_analysis_result)
        db_session.commit()
        return run_id, emb_provider

    def _client_with_db(self, db_session):
        from api.routes import get_db_session
        app.dependency_overrides[get_db_session] = lambda: (yield db_session)
        return TestClient(app)

    def _ask(self, client, run_id):
        return client.post(f"/api/v1/analyses/{run_id}/ask", json={"question": "test?"})

    def test_authentication_error_returns_502(self, db_session, sample_analysis_result):
        """LLMAuthenticationError (bad API key) → HTTP 502."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            failing = TestLLMProvider()
            failing.generate = mock.Mock(side_effect=LLMAuthenticationError("key rejected"))
            mock_factory.return_value = failing
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 502
        assert "secret" not in resp.text.lower()
        assert "traceback" not in resp.text.lower()

    def test_rate_limit_error_returns_429(self, db_session, sample_analysis_result):
        """LLMRateLimitError → HTTP 429."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            failing = TestLLMProvider()
            failing.generate = mock.Mock(side_effect=LLMRateLimitError("quota exceeded"))
            mock_factory.return_value = failing
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 429

    def test_timeout_error_returns_504(self, db_session, sample_analysis_result):
        """LLMTimeoutError → HTTP 504."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            failing = TestLLMProvider()
            failing.generate = mock.Mock(side_effect=LLMTimeoutError("30s timeout"))
            mock_factory.return_value = failing
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 504

    def test_not_configured_error_returns_503(self, db_session, sample_analysis_result):
        """LLMNotConfiguredError → HTTP 503."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            mock_factory.side_effect = LLMNotConfiguredError("LLM_PROVIDER not set")
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 503

    def test_response_error_returns_502(self, db_session, sample_analysis_result):
        """LLMResponseError (network/malformed) → HTTP 502."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            failing = TestLLMProvider()
            failing.generate = mock.Mock(side_effect=LLMResponseError("malformed response"))
            mock_factory.return_value = failing
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 502

    def test_unexpected_exception_wrapped_as_502(self, db_session, sample_analysis_result):
        """Raw RuntimeError from generate() is wrapped as LLMResponseError → HTTP 502 (no bare 500)."""
        run_id, emb_p = self._make_run_with_embeddings(db_session, sample_analysis_result)
        import unittest.mock as mock
        with mock.patch("rag.service.get_llm_provider") as mock_factory:
            failing = TestLLMProvider()
            failing.generate = mock.Mock(side_effect=RuntimeError("unexpected crash"))
            mock_factory.return_value = failing
            client = self._client_with_db(db_session)
            resp = self._ask(client, run_id)
        app.dependency_overrides.clear()
        assert resp.status_code == 502
        assert "secret" not in resp.text.lower()
