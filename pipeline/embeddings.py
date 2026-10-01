"""
Embedding provider abstraction for repository code evidence chunking (Session 20).

Provides a lightweight, interchangeable interface for embedding source chunks and search queries.
Includes:
  - Base Abstract EmbeddingProvider interface
  - TestEmbeddingProvider: Deterministic, fast, offline vector generator for unit testing & CI.
  - SentenceTransformerProvider: Optional local embedding provider (all-MiniLM-L6-v2) if installed.
  - get_embedding_provider: Factory helper resolving provider based on environment config.
"""
from __future__ import annotations

import abc
import hashlib
import math
import os
import sys
from typing import List, Optional

EMBEDDING_PIPELINE_VERSION = "1"


class BaseEmbeddingProvider(abc.ABC):
    """Abstract interface for embedding providers."""

    name: str
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

        self.name = "test-deterministic"
        self.model_version = "1.0"
        self.dimension = dimension

    def _hash_vector(self, text: str) -> List[float]:
        """Convert string text into a deterministic, unit-normalized vector of size self.dimension."""
        vec = []
        # Generate enough bytes from hashing iterations
        seed = text.encode("utf-8")
        iteration = 0
        while len(vec) < self.dimension:
            hasher = hashlib.sha256(seed + str(iteration).encode("utf-8"))
            digest = hasher.digest()
            for i in range(0, len(digest), 4):
                if len(vec) >= self.dimension:
                    break
                # Convert 4 bytes into float in [-1.0, 1.0]
                val = int.from_bytes(digest[i:i+4], byteorder="big", signed=True) / (2**31 - 1)
                vec.append(val)
            iteration += 1

        # Normalize vector to unit length
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
    Falls back gracefully to TestEmbeddingProvider if sentence-transformers is not installed.
    Configured via EMBEDDING_MODEL_NAME env var (default: all-MiniLM-L6-v2).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Allow env override at construction time
        resolved_model = os.environ.get("EMBEDDING_MODEL_NAME", model_name)
        self.name = resolved_model
        self.model_version = "1.0"
        self._available = False
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(resolved_model)
            self.dimension = self._model.get_sentence_embedding_dimension() or 384
            self._available = True
        except ImportError:
            print(
                f"[embeddings warning] 'sentence-transformers' package not installed. "
                f"Install it with: pip install sentence-transformers",
                file=sys.stderr,
            )
            self._init_fallback(resolved_model)
        except Exception as exc:
            print(f"[embeddings warning] Could not load SentenceTransformer '{resolved_model}': {exc}", file=sys.stderr)
            self._init_fallback(resolved_model)

    def _init_fallback(self, original_model_name: str) -> None:
        """Initialize as fallback TestEmbeddingProvider when the real model is unavailable."""
        fallback = TestEmbeddingProvider()
        self.name = fallback.name
        self.model_version = fallback.model_version
        self.dimension = fallback.dimension
        self._model = None

    @property
    def is_available(self) -> bool:
        """Returns True if the real sentence-transformers model loaded successfully."""
        return self._available

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if self._model is None:
            return TestEmbeddingProvider(self.dimension).embed_documents(texts)
        embeddings = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        if self._model is None:
            return TestEmbeddingProvider(self.dimension).embed_query(text)
        embedding = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.tolist()


# Recognized provider name aliases — canonical name is first in each group
_SENTENCE_TRANSFORMER_ALIASES = frozenset({
    "sentence_transformers",   # documented in .env.example
    "sentence-transformers",   # hyphenated variant
    "sentence_transformer",    # singular
    "sentence-transformer",    # hyphenated singular
    "minilm",
    "all-minilm-l6-v2",
    "all_minilm_l6_v2",
})


def get_embedding_provider(provider_name: Optional[str] = None) -> BaseEmbeddingProvider:
    """
    Factory function to retrieve embedding provider instance.
    Checks environment variable EMBEDDING_PROVIDER if not passed explicitly.
    In testing environment (PYTEST_CURRENT_TEST set), defaults to TestEmbeddingProvider.

    Recognized EMBEDDING_PROVIDER values:
      - "test" / "deterministic" / "mock"  → TestEmbeddingProvider (offline, CI-safe)
      - "sentence_transformers" (or variants) → SentenceTransformerProvider (local model)
    """
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TESTING"):
        return TestEmbeddingProvider()

    p_name = provider_name or os.environ.get("EMBEDDING_PROVIDER", "test")
    p_name_lower = p_name.strip().lower()

    if p_name_lower in ("test", "deterministic", "mock"):
        return TestEmbeddingProvider()
    elif p_name_lower in _SENTENCE_TRANSFORMER_ALIASES:
        model_name = os.environ.get("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        return SentenceTransformerProvider(model_name)

    # Default fallback for unknown/unconfigured provider — safe for offline/test use
    print(
        f"[embeddings warning] Unknown EMBEDDING_PROVIDER '{p_name}'. "
        f"Falling back to TestEmbeddingProvider. "
        f"Valid options: test, sentence_transformers.",
        file=sys.stderr,
    )
    return TestEmbeddingProvider()


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
