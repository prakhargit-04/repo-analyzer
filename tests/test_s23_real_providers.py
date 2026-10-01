"""
Session 23 — Real Provider Integration Tests.

Covers:
  A) Embedding provider factory (get_embedding_provider)
       - All recognised name aliases resolve correctly
       - "sentence_transformers" (underscore) variant — the documented env name
       - EMBEDDING_MODEL_NAME env var is respected
       - Unknown provider name falls back to TestEmbeddingProvider with a warning
       - is_available property reflects load success / fallback state
  B) format_chunk_for_embedding — contract & idempotency
  C) LLM provider factory (get_llm_provider)
       - "test" / "mock" / "deterministic" resolve to TestLLMProvider
       - "openai" resolves to OpenAILLMProvider
       - "gemini" / "google" resolve to GeminiLLMProvider
       - OpenAI/Gemini providers raise RuntimeError when API key is absent
  D) SentenceTransformerProvider graceful fallback
       - When sentence-transformers is NOT installed the provider silently falls
         back to TestEmbeddingProvider (never crashes)
"""
from __future__ import annotations

import io
import os
import sys
import importlib
import unittest.mock as mock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from embeddings import (
    TestEmbeddingProvider,
    SentenceTransformerProvider,
    get_embedding_provider,
    format_chunk_for_embedding,
    _SENTENCE_TRANSFORMER_ALIASES,
)
from rag.llm import (
    TestLLMProvider,
    OpenAILLMProvider,
    GeminiLLMProvider,
    get_llm_provider,
)


# ---------------------------------------------------------------------------
# Helper — clear PYTEST_CURRENT_TEST so factory doesn't short-circuit to test
# ---------------------------------------------------------------------------

class _NoPytest:
    """Context manager that hides PYTEST_CURRENT_TEST from the provider factory."""

    def __enter__(self):
        self._saved = os.environ.pop("PYTEST_CURRENT_TEST", None)
        return self

    def __exit__(self, *_):
        if self._saved is not None:
            os.environ["PYTEST_CURRENT_TEST"] = self._saved


# ===========================================================================
# A) Embedding provider factory
# ===========================================================================

class TestEmbeddingProviderFactory:
    """get_embedding_provider factory name resolution."""

    def test_test_alias_resolves_to_test_provider(self):
        with _NoPytest():
            p = get_embedding_provider("test")
        assert isinstance(p, TestEmbeddingProvider)

    def test_mock_alias_resolves_to_test_provider(self):
        with _NoPytest():
            p = get_embedding_provider("mock")
        assert isinstance(p, TestEmbeddingProvider)

    def test_deterministic_alias_resolves_to_test_provider(self):
        with _NoPytest():
            p = get_embedding_provider("deterministic")
        assert isinstance(p, TestEmbeddingProvider)

    def test_sentence_transformers_underscore_resolves(self):
        """Critical: documented env value uses underscore, must not fall through to test."""
        with _NoPytest():
            p = get_embedding_provider("sentence_transformers")
        assert isinstance(p, SentenceTransformerProvider)

    def test_sentence_transformers_hyphen_resolves(self):
        with _NoPytest():
            p = get_embedding_provider("sentence-transformers")
        assert isinstance(p, SentenceTransformerProvider)

    def test_minilm_alias_resolves(self):
        with _NoPytest():
            p = get_embedding_provider("minilm")
        assert isinstance(p, SentenceTransformerProvider)

    def test_all_aliases_in_frozenset_resolve(self):
        """Every documented alias in _SENTENCE_TRANSFORMER_ALIASES must resolve."""
        for alias in _SENTENCE_TRANSFORMER_ALIASES:
            with _NoPytest():
                p = get_embedding_provider(alias)
            assert isinstance(p, SentenceTransformerProvider), (
                f"Alias '{alias}' did not resolve to SentenceTransformerProvider"
            )

    def test_unknown_provider_falls_back_to_test(self, capsys):
        with _NoPytest():
            p = get_embedding_provider("totally-unknown-provider-xyz")
        assert isinstance(p, TestEmbeddingProvider)
        # Warning must be printed to stderr
        captured = capsys.readouterr()
        assert "Unknown EMBEDDING_PROVIDER" in captured.err or "warning" in captured.err.lower()

    def test_env_var_drives_selection(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence_transformers")
        p = get_embedding_provider()
        assert isinstance(p, SentenceTransformerProvider)

    def test_env_model_name_respected(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        p = get_embedding_provider("sentence_transformers")
        assert isinstance(p, SentenceTransformerProvider)

    def test_whitespace_in_provider_name_stripped(self):
        """Provider name with surrounding whitespace must still resolve."""
        with _NoPytest():
            p = get_embedding_provider("  test  ")
        assert isinstance(p, TestEmbeddingProvider)


# ===========================================================================
# B) SentenceTransformerProvider fallback when package absent
# ===========================================================================

class TestSentenceTransformerFallback:
    """Validates graceful degradation when sentence-transformers is not installed."""

    def _make_fallback_provider(self) -> SentenceTransformerProvider:
        """Build a SentenceTransformerProvider in fallback state without importing the lib."""
        p = SentenceTransformerProvider.__new__(SentenceTransformerProvider)
        p._available = False
        p._model = None
        p.name = "test-deterministic"
        p.model_version = "1.0"
        p.dimension = 64
        return p

    def test_is_available_false_when_model_not_loaded(self):
        """is_available property must be False when _model is None (fallback state)."""
        p = self._make_fallback_provider()
        assert p.is_available is False

    def test_embed_documents_fallback_returns_correct_dimension(self):
        """Fallback embed_documents produces correct-dimension vectors."""
        p = self._make_fallback_provider()
        vecs = p.embed_documents(["function authenticate(user, pwd):", "def compute_score():"])
        assert len(vecs) == 2
        for v in vecs:
            assert len(v) == 64

    def test_embed_query_fallback_returns_correct_dimension(self):
        p = self._make_fallback_provider()
        vec = p.embed_query("Where is authentication implemented?")
        assert len(vec) == 64

    def test_embed_documents_fallback_is_deterministic(self):
        """Fallback vectors must be identical across calls for same input."""
        p = self._make_fallback_provider()
        v1 = p.embed_documents(["hello world"])
        v2 = p.embed_documents(["hello world"])
        assert v1 == v2


# ===========================================================================
# B2) format_chunk_for_embedding — contract
# ===========================================================================

class TestFormatChunkForEmbedding:
    """format_chunk_for_embedding output contract and idempotency."""

    _FULL_CHUNK = {
        "file_path": "src/auth.py",
        "language": "python",
        "start_line": 15,
        "end_line": 35,
        "entity_name": "authenticate",
        "entity_type": "function",
        "chunk_text": "def authenticate(user, password):\n    return verify_user(user, password)",
    }

    def test_includes_file_path(self):
        out = format_chunk_for_embedding(self._FULL_CHUNK)
        assert "src/auth.py" in out

    def test_includes_language(self):
        out = format_chunk_for_embedding(self._FULL_CHUNK)
        assert "python" in out

    def test_includes_line_range(self):
        out = format_chunk_for_embedding(self._FULL_CHUNK)
        assert "15" in out
        assert "35" in out

    def test_includes_entity_info(self):
        out = format_chunk_for_embedding(self._FULL_CHUNK)
        assert "authenticate" in out
        assert "function" in out

    def test_includes_chunk_text(self):
        out = format_chunk_for_embedding(self._FULL_CHUNK)
        assert "def authenticate" in out

    def test_idempotent(self):
        """Same chunk always produces identical formatted text."""
        out1 = format_chunk_for_embedding(self._FULL_CHUNK)
        out2 = format_chunk_for_embedding(self._FULL_CHUNK)
        assert out1 == out2

    def test_missing_entity_graceful(self):
        chunk = {
            "file_path": "src/util.py",
            "language": "python",
            "start_line": 1,
            "end_line": 10,
            "chunk_text": "# utility module",
        }
        out = format_chunk_for_embedding(chunk)
        assert "src/util.py" in out
        assert "utility module" in out

    def test_empty_chunk_text_graceful(self):
        chunk = {
            "file_path": "src/empty.py",
            "language": "python",
            "start_line": 1,
            "end_line": 1,
            "chunk_text": "",
        }
        out = format_chunk_for_embedding(chunk)
        assert "src/empty.py" in out

    def test_missing_language_defaults_unknown(self):
        chunk = {"file_path": "src/x.py", "start_line": 1, "end_line": 5, "chunk_text": "pass"}
        out = format_chunk_for_embedding(chunk)
        assert "unknown" in out


# ===========================================================================
# C) LLM provider factory
# ===========================================================================

class TestLLMProviderFactory:
    """get_llm_provider factory resolution."""

    def test_test_resolves_to_test_llm(self):
        with _NoPytest():
            p = get_llm_provider("test")
        assert isinstance(p, TestLLMProvider)

    def test_mock_resolves_to_test_llm(self):
        with _NoPytest():
            p = get_llm_provider("mock")
        assert isinstance(p, TestLLMProvider)

    def test_deterministic_resolves_to_test_llm(self):
        with _NoPytest():
            p = get_llm_provider("deterministic")
        assert isinstance(p, TestLLMProvider)

    def test_openai_resolves_to_openai_provider(self):
        with _NoPytest():
            p = get_llm_provider("openai")
        assert isinstance(p, OpenAILLMProvider)

    def test_gemini_resolves_to_gemini_provider(self):
        with _NoPytest():
            p = get_llm_provider("gemini")
        assert isinstance(p, GeminiLLMProvider)

    def test_google_alias_resolves_to_gemini_provider(self):
        with _NoPytest():
            p = get_llm_provider("google")
        assert isinstance(p, GeminiLLMProvider)

    def test_unknown_provider_falls_back_to_test_llm(self):
        with _NoPytest():
            p = get_llm_provider("nonexistent-llm-xyz")
        assert isinstance(p, TestLLMProvider)

    def test_env_var_drives_llm_selection(self, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("LLM_PROVIDER", "test")
        p = get_llm_provider()
        assert isinstance(p, TestLLMProvider)


# ===========================================================================
# D) OpenAI / Gemini provider key-guard
# ===========================================================================

class TestRealProviderKeyGuard:
    """Real API providers must raise RuntimeError when API key is missing."""

    def test_openai_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        p = OpenAILLMProvider()
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            p.generate("test prompt")

    def test_gemini_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        p = GeminiLLMProvider()
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            p.generate("test prompt")

    def test_openai_provider_name(self):
        p = OpenAILLMProvider()
        assert p.name == "openai"

    def test_gemini_provider_name(self):
        p = GeminiLLMProvider()
        assert p.name == "gemini"

    def test_openai_default_model(self):
        p = OpenAILLMProvider()
        assert "gpt" in p.model_name.lower()

    def test_gemini_default_model(self):
        p = GeminiLLMProvider()
        assert "gemini" in p.model_name.lower()

    def test_openai_custom_model(self):
        p = OpenAILLMProvider(model_name="gpt-4o")
        assert p.model_name == "gpt-4o"

    def test_gemini_custom_model(self):
        p = GeminiLLMProvider(model_name="gemini-1.5-pro")
        assert p.model_name == "gemini-1.5-pro"
