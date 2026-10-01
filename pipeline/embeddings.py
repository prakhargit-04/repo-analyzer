"""
Embedding provider abstraction for repository code evidence chunking (Session 20 & Session 23).

Provides a lightweight, interchangeable interface for embedding source chunks and search queries.
Includes:
  - Base Abstract EmbeddingProvider interface
  - TestEmbeddingProvider: Deterministic, fast, offline vector generator for unit testing & CI.
  - SentenceTransformerProvider: Optional local embedding provider (all-MiniLM-L6-v2) if installed.
  - get_embedding_provider: Cached factory helper resolving provider based on environment config.
"""
from __future__ import annotations

import abc
import hashlib
import math
import os
import sys
from typing import List, Optional

EMBEDDING_PIPELINE_VERSION = "1"

# Recognized provider name aliases — canonical name is first
_SENTENCE_TRANSFORMER_ALIASES = frozenset({
    "sentence_transformers",   # documented in .env.example
    "sentence-transformers",   # hyphenated variant
    "sentence_transformer",    # singular
    "sentence-transformer",    # hyphenated singular
    "minilm",
    "all-minilm-l6-v2",
    "all_minilm_l6_v2",
})


class BaseEmbeddingProvider(abc.ABC):
    """Abstract interface for embedding providers."""

    provider_id: str
    name: str
    model_name: str
    model_version: str
    dimension: int

    @abc.abstractmethod
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of document/chunk texts into a list of floating point vectors."""
        pass

    @abc.abstractmethod
    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string into a floating point vector."""
        pass


class TestEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic test embedding provider.
    Generates reproducible unit-normalized vectors from string SHA-256 hashes.
    Does not require external APIs, GPU, or model weights.
    """
    __test__ = False

    def __init__(self, dimension: int = 64):
        self.provider_id = "test"
        self.name = "test-deterministic"
        self.model_name = "test-deterministic"
        self.model_version = "1.0"
        self.dimension = dimension

    def _hash_vector(self, text: str) -> List[float]:
        """Convert string text into a deterministic, unit-normalized vector of size self.dimension."""
        vec = []
        seed = text.encode("utf-8")
        iteration = 0
        while len(vec) < self.dimension:
            hasher = hashlib.sha256(seed + str(iteration).encode("utf-8"))
            digest = hasher.digest()
            for i in range(0, len(digest), 4):
                if len(vec) >= self.dimension:
                    break
                val = int.from_bytes(digest[i:i+4], byteorder="big", signed=True) / (2**31 - 1)
                vec.append(val)
            iteration += 1

        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return [1.0 / math.sqrt(self.dimension)] * self.dimension
        return [x / norm for x in vec]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_vector(t) for t in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._hash_vector(text)


class SentenceTransformerProvider(BaseEmbeddingProvider):
    """
    SentenceTransformers local model provider (e.g. all-MiniLM-L6-v2).
    Fails fast if sentence-transformers is not installed or model cannot be loaded.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        resolved_model = os.environ.get("EMBEDDING_MODEL_NAME", model_name)
        self.provider_id = "sentence_transformers"
        self.name = "sentence_transformers"
        self.model_name = resolved_model
        self.model_version = "1.0"

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ValueError(
                "Package 'sentence-transformers' is not installed. "
                "Install it with: pip install sentence-transformers"
            ) from exc

        try:
            self._model = SentenceTransformer(resolved_model)
            self.dimension = self._model.get_sentence_embedding_dimension() or 384
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load SentenceTransformer model '{resolved_model}': {exc}"
            ) from exc

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        embedding = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.tolist()


_CACHED_EMBEDDING_PROVIDER: Optional[BaseEmbeddingProvider] = None
_CACHED_EMBEDDING_KEY: Optional[tuple] = None


def reset_embedding_provider_cache() -> None:
    """Clear the cached embedding provider instance."""
    global _CACHED_EMBEDDING_PROVIDER, _CACHED_EMBEDDING_KEY
    _CACHED_EMBEDDING_PROVIDER = None
    _CACHED_EMBEDDING_KEY = None


def get_embedding_provider(
    provider_name: Optional[str] = None,
    force_reload: bool = False,
) -> BaseEmbeddingProvider:
    """
    Factory function to retrieve cached embedding provider instance.
    Checks environment variable EMBEDDING_PROVIDER if not passed explicitly.
    Default (unconfigured) provider is TestEmbeddingProvider.

    Recognized EMBEDDING_PROVIDER values:
      - "test" / "deterministic" / "mock"  → TestEmbeddingProvider (offline, CI-safe)
      - "sentence_transformers" (or variants) → SentenceTransformerProvider (local model)

    Raises ValueError / RuntimeError if explicitly requested real provider is unavailable or invalid.
    """
    global _CACHED_EMBEDDING_PROVIDER, _CACHED_EMBEDDING_KEY

    p_name = provider_name or os.environ.get("EMBEDDING_PROVIDER")
    if not p_name:
        p_name = "test"

    p_name_clean = p_name.strip().lower()
    model_name = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2") if p_name_clean in _SENTENCE_TRANSFORMER_ALIASES else "sha256-deterministic"
    cache_key = (p_name_clean, model_name)

    if not force_reload and _CACHED_EMBEDDING_PROVIDER is not None and _CACHED_EMBEDDING_KEY == cache_key:
        return _CACHED_EMBEDDING_PROVIDER

    if p_name_clean in ("test", "deterministic", "mock"):
        instance = TestEmbeddingProvider()
    elif p_name_clean in _SENTENCE_TRANSFORMER_ALIASES:
        instance = SentenceTransformerProvider(model_name)
    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER '{p_name}'. "
            f"Valid options: 'test', 'sentence_transformers'."
        )

    _CACHED_EMBEDDING_PROVIDER = instance
    _CACHED_EMBEDDING_KEY = cache_key
    return instance


def get_embedding_version(provider: BaseEmbeddingProvider) -> str:
    """
    Returns conceptual provider:model:dimension version identifier.
    Guarantees different provider, model, or dimension produces different string version.
    """
    p_id = getattr(provider, "provider_id", getattr(provider, "name", "unknown"))
    m_name = getattr(provider, "model_name", getattr(provider, "name", "unknown"))
    dim = getattr(provider, "dimension", 0)
    return f"{p_id}:{m_name}:{dim}"


def format_chunk_for_embedding(chunk: dict) -> str:
    """
    Formats a SourceChunk dict into a structured, contextual text representation for embedding.
    Includes file path, language, entity metadata (if available), line range, and source text.
    Ensures identical chunk produces identical text.
    """
    fp = chunk.get("file_path", "")
    lang = chunk.get("language", "unknown")
    start_line = chunk.get("start_line", 1)
    end_line = chunk.get("end_line", 1)
    
    entity_name = chunk.get("entity_name")
    entity_type = chunk.get("entity_type")
    
    lines_header = f"lines: {start_line}-{end_line}"
    entity_header = f"entity: {entity_type} {entity_name}\n" if entity_name else ""
    
    body = chunk.get("chunk_text", "")
    
    return f"file: {fp}\nlanguage: {lang}\n{entity_header}{lines_header}\n\n{body}"
