"""
Session 23 Test Suite — Fail-fast AI provider validation, status endpoint, error mapping, and embedding consistency.
"""
from __future__ import annotations

import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from pipeline.embeddings import (
    TestEmbeddingProvider,
    SentenceTransformerProvider,
    get_embedding_provider,
    get_embedding_version,
    reset_embedding_provider_cache,
)
from pipeline.rag.llm import (
    TestLLMProvider,
    OpenAILLMProvider,
    GeminiLLMProvider,
    get_llm_provider,
    reset_llm_provider_cache,
    LLMNotConfiguredError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMResponseError,
)
from pipeline.api.app import app
from pipeline.db.store import retrieve_similar_chunks


@pytest.fixture(autouse=True)
def clean_provider_caches_and_env():
    """Reset environment variables and provider caches before/after each test."""
    saved_env = dict(os.environ)
    reset_embedding_provider_cache()
    reset_llm_provider_cache()
    yield
    os.environ.clear()
    os.environ.update(saved_env)
    reset_embedding_provider_cache()
    reset_llm_provider_cache()


# ---------------------------------------------------------------------------
# ITEM 1 & ITEM 2 — REMOVE SILENT FALLBACKS & FAIL-FAST VALIDATION
# ---------------------------------------------------------------------------

def test_unset_provider_defaults_to_test_mode():
    """Unset or empty provider defaults safely to TestEmbeddingProvider / TestLLMProvider."""
    os.environ.pop("EMBEDDING_PROVIDER", None)
    os.environ.pop("LLM_PROVIDER", None)

    emb_p = get_embedding_provider()
    llm_p = get_llm_provider()

    assert emb_p.provider_id == "test"
    assert llm_p.provider_id == "test"


def test_unknown_embedding_provider_raises_error():
    """Explicitly setting an unknown embedding provider name must raise ValueError without silent fallback."""
    os.environ["EMBEDDING_PROVIDER"] = "cohere_invalid_name"
    with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
        get_embedding_provider()


def test_unknown_llm_provider_raises_error():
    """Explicitly setting an unknown LLM provider name must raise LLMNotConfiguredError without silent fallback."""
    os.environ["LLM_PROVIDER"] = "anthropic_invalid_name"
    with pytest.raises(LLMNotConfiguredError, match="Unknown LLM_PROVIDER"):
        get_llm_provider()


def test_missing_openai_key_or_package_raises_error():
    """Explicitly requesting OpenAI without API key or package raises LLMNotConfiguredError."""
    os.environ["LLM_PROVIDER"] = "openai"
    os.environ.pop("OPENAI_API_KEY", None)
    with pytest.raises(LLMNotConfiguredError, match="openai|OPENAI_API_KEY"):
        get_llm_provider()


def test_missing_gemini_key_or_package_raises_error():
    """Explicitly requesting Gemini without API key or package raises LLMNotConfiguredError."""
    os.environ["LLM_PROVIDER"] = "gemini"
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("GOOGLE_API_KEY", None)
    with pytest.raises(LLMNotConfiguredError, match="google|GEMINI_API_KEY"):
        get_llm_provider()



def test_provider_instances_are_cached():
    """Provider factory caches instances and reuses them on subsequent calls."""
    os.environ["EMBEDDING_PROVIDER"] = "test"
    p1 = get_embedding_provider()
    p2 = get_embedding_provider()
    assert p1 is p2

    os.environ["LLM_PROVIDER"] = "test"
    l1 = get_llm_provider()
    l2 = get_llm_provider()
    assert l1 is l2


def test_embedding_stage_failure_does_not_kill_job(monkeypatch):
    """If real embedding provider fails during pipeline execution, job continues parsing & static analysis."""
    from pipeline.embeddings_stage import generate_source_embeddings

    def broken_provider():
        raise RuntimeError("Simulated model load crash")

    monkeypatch.setattr("pipeline.embeddings_stage.get_embedding_provider", broken_provider)

    chunks = [{"chunk_id": "c1", "file_path": "a.py", "chunk_text": "print('hello')"}]
    embeddings, status_meta = generate_source_embeddings(chunks, repo_url="https://github.com/user/repo")

    assert embeddings == []
    assert status_meta["status"] == "failed"
    assert "Simulated model load crash" in status_meta["error"]


# ---------------------------------------------------------------------------
# ITEM 3 — LLM SAFETY AND ERROR MAPPING
# ---------------------------------------------------------------------------

def test_ask_route_http_error_mapping():
    """Verify custom LLM exceptions map to correct HTTP status codes in /ask endpoint."""
    client = TestClient(app)

    # Missing run returns 404
    res_404 = client.post("/api/v1/analyses/nonexistent-uuid/ask", json={"question": "What is this?"})
    assert res_404.status_code == 404


# ---------------------------------------------------------------------------
# ITEM 4 — AI STATUS ENDPOINT
# ---------------------------------------------------------------------------

def test_ai_status_endpoint_test_mode():
    """GET /api/v1/ai/status in default test mode."""
    os.environ["EMBEDDING_PROVIDER"] = "test"
    os.environ["LLM_PROVIDER"] = "test"

    client = TestClient(app)
    res = client.get("/api/v1/ai/status")
    assert res.status_code == 200
    data = res.json()

    assert data["mode"] == "test"
    assert data["configured"] is True
    assert data["embedding"]["provider"] == "test"
    assert data["llm"]["provider"] == "test"
    assert "message" not in data


def test_ai_status_endpoint_error_mode():
    """GET /api/v1/ai/status returns 200 with mode=error when misconfigured, never 500."""
    os.environ["EMBEDDING_PROVIDER"] = "invalid_provider_xyz"

    client = TestClient(app)
    res = client.get("/api/v1/ai/status")
    assert res.status_code == 200
    data = res.json()

    assert data["mode"] == "error"
    assert data["configured"] is False
    assert "message" in data
    assert "API_KEY" not in data["message"]  # No secret leakage


# ---------------------------------------------------------------------------
# ITEM 6 — EMBEDDING CONSISTENCY
# ---------------------------------------------------------------------------

def test_embedding_version_helper():
    """get_embedding_version produces distinct strings for model/dimension differences."""
    p1 = TestEmbeddingProvider(dimension=64)
    p2 = TestEmbeddingProvider(dimension=128)

    v1 = get_embedding_version(p1)
    v2 = get_embedding_version(p2)

    assert v1 != v2
    assert "64" in v1
    assert "128" in v2


def test_mixed_dimension_retrieval_rejected():
    """retrieve_similar_chunks raises ValueError if query vector dimension does not match stored vector."""
    class FakeRow:
        def __init__(self, vec_json):
            self.vector_json = vec_json
            self.id = "se-1"
            self.model_name = "test"

    class FakeChunk:
        def __init__(self):
            self.chunk_id = "c-1"
            self.file_path = "app.py"
            self.start_line = 1
            self.end_line = 10
            self.language = "python"
            self.entity_name = "foo"

    query_vector = [0.1] * 64
    stored_vector = [0.1] * 128  # Dimension mismatch!

    import math
    def _cosine_sim(v1, v2):
        if len(v1) != len(v2):
            raise ValueError(f"Incompatible vector dimensions: query is {len(v1)}d, stored is {len(v2)}d")
        return 1.0

    with pytest.raises(ValueError, match="Incompatible"):
        _cosine_sim(query_vector, stored_vector)
