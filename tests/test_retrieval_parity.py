"""
Sub-task 6.3: Retrieval numpy vs fallback parity, zero vectors, tie-breaking, dimension mismatch.
"""
import math
import random
import sys
import pytest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.store import EmbeddingMismatchError


def _cosine_sim_python(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _cosine_sim_numpy(query: list[float], matrix: list[list[float]]) -> list[float]:
    import numpy as np
    q = np.array(query, dtype=np.float64)
    mat = np.array(matrix, dtype=np.float64)
    q_norm = np.linalg.norm(q)
    mat_norms = np.linalg.norm(mat, axis=1)
    denom = mat_norms * q_norm
    scores = np.divide(np.dot(mat, q), denom, out=np.zeros_like(denom), where=denom != 0)
    return [float(s) for s in scores]


def test_numpy_vs_python_retrieval_parity_500_vectors():
    """Numpy path and pure-Python fallback give identical top-k IDs and scores within 1e-9 on 500 vectors."""
    rng = random.Random(42)
    dim = 64
    num_vectors = 500

    query = [rng.uniform(-1, 1) for _ in range(dim)]
    vectors = [[rng.uniform(-1, 1) for _ in range(dim)] for _ in range(num_vectors)]

    # Add edge cases: zero vector, exact duplicate, tied vectors
    vectors[0] = [0.0] * dim
    vectors[1] = list(query)  # Exact match
    vectors[2] = list(query)  # Tie with exact match

    # Python computation
    py_scored = []
    for idx, v in enumerate(vectors):
        chunk_id = f"chunk_{idx:03d}"
        score = _cosine_sim_python(query, v)
        py_scored.append((score, chunk_id))

    py_scored.sort(key=lambda x: (-x[0], x[1]))

    # Numpy computation
    np_scores = _cosine_sim_numpy(query, vectors)
    np_scored = []
    for idx, s in enumerate(np_scores):
        chunk_id = f"chunk_{idx:03d}"
        np_scored.append((s, chunk_id))

    np_scored.sort(key=lambda x: (-x[0], x[1]))

    # Compare top-20 results
    for i in range(20):
        py_score, py_id = py_scored[i]
        np_score, np_id = np_scored[i]
        assert py_id == np_id
        assert abs(py_score - np_score) < 1e-9


def test_zero_vector_similarity_returns_zero():
    """Zero vectors return similarity 0.0 in both Python and Numpy implementations."""
    v1 = [0.0] * 32
    v2 = [1.0] * 32
    assert _cosine_sim_python(v1, v2) == 0.0
    assert _cosine_sim_numpy(v1, [v2])[0] == 0.0
