"""
Pipeline stage for generating embeddings from SourceChunk objects (Session 20).

Orchestrates batching, structured formatting, provider execution, and error safety.
"""
from __future__ import annotations

import os
import sys

from typing import Any, Dict, List, Optional, Tuple

from embeddings import (
    BaseEmbeddingProvider,
    EMBEDDING_PIPELINE_VERSION,
    format_chunk_for_embedding,
    get_embedding_provider,
)


def generate_source_embeddings(
    source_chunks: List[Dict[str, Any]],
    repo_url: str,
    commit_sha: Optional[str] = None,
    provider: Optional[BaseEmbeddingProvider] = None,
    batch_size: int = 32,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Generates embedding vectors for a list of canonical SourceChunk dicts.

    Args:
        source_chunks: List of SourceChunk dictionary objects.
        repo_url: Repository identifier URL or path.
        commit_sha: Optional commit SHA.
        provider: Optional custom BaseEmbeddingProvider instance.
        batch_size: Number of chunks per batch call to embed_documents.

    Returns:
        Tuple of (embeddings_list, status_dict):
          - embeddings_list: List of dicts ready for SourceEmbedding model persistence.
          - status_dict: Metadata describing the result ("status": "completed" | "failed" | "empty").
    """
    if not source_chunks:
        return [], {
            "status": "completed",
            "total_embeddings": 0,
            "provider_name": "none",
            "model_version": "none",
            "dimension": 0,
        }

    try:
        active_provider = provider or get_embedding_provider()
    except Exception as exc:
        print(f"[embeddings stage warning] Embedding provider initialization failed: {exc}", file=sys.stderr)
        return [], {
            "status": "failed",
            "error": str(exc),
            "total_embeddings": 0,
            "provider_name": os.environ.get("EMBEDDING_PROVIDER", "unknown"),

            "model_version": "unknown",
            "dimension": 0,
        }

    formatted_texts: List[str] = []
    chunk_meta_list: List[Dict[str, Any]] = []

    for sc in source_chunks:
        formatted_texts.append(format_chunk_for_embedding(sc))
        chunk_meta_list.append(sc)

    vectors: List[List[float]] = []
    try:
        # Process in batches
        for i in range(0, len(formatted_texts), batch_size):
            batch_texts = formatted_texts[i : i + batch_size]
            batch_vectors = active_provider.embed_documents(batch_texts)
            vectors.extend(batch_vectors)
    except Exception as exc:
        print(f"[embeddings stage warning] Embedding generation failed: {exc}", file=sys.stderr)
        return [], {
            "status": "failed",
            "error": str(exc),
            "total_embeddings": 0,
            "provider_name": active_provider.name,
            "model_version": active_provider.model_version,
            "dimension": getattr(active_provider, "dimension", 0),
        }


    embeddings_result: List[Dict[str, Any]] = []
    for sc, vec in zip(chunk_meta_list, vectors):
        embeddings_result.append({
            "source_chunk_id": sc.get("id") or sc.get("chunk_id"),
            "chunk_id": sc.get("chunk_id"),
            "repo_url": repo_url,
            "commit_sha": sc.get("commit_sha") or commit_sha,
            "model_name": active_provider.name,
            "model_version": active_provider.model_version,
            "dimension": len(vec),
            "pipeline_version": EMBEDDING_PIPELINE_VERSION,
            "vector": vec,
        })

    return embeddings_result, {
        "status": "completed",
        "total_embeddings": len(embeddings_result),
        "provider_name": active_provider.name,
        "model_version": active_provider.model_version,
        "dimension": active_provider.dimension,
        "pipeline_version": EMBEDDING_PIPELINE_VERSION,
    }
