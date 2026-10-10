"""
Sub-task 6.4: RAG evidence budget, truncation, and citation validation tests.
"""
import sys
import pytest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rag.context_builder import build_evidence_context, build_rag_user_prompt
from rag.citation_validator import validate_citations


def test_zero_chunks_returns_empty_context():
    """Zero retrieved chunks returns default notice and empty evidence map."""
    ctx, ev_map = build_evidence_context([])
    assert ctx == "No relevant repository evidence found."
    assert ev_map == {}


def test_rag_evidence_budget_and_contiguous_ids():
    """20 chunks fitted within evidence character budget with contiguous E1..En IDs."""
    chunks = [
        {
            "chunk_id": f"c_{i}",
            "file_path": f"src/file_{i}.py",
            "start_line": 1,
            "end_line": 100,
            "language": "python",
            "chunk_text": f"# line {i}\n" * 100,
        }
        for i in range(20)
    ]

    budget = 4000
    ctx, ev_map = build_evidence_context(chunks, max_evidence_chars=budget)

    # Total evidence length <= budget
    assert len(ctx) <= budget + 100  # allow header wrapper
    assert "E1" in ev_map
    assert len(ev_map) > 0

    # Contiguous keys E1..En
    keys = list(ev_map.keys())
    expected_keys = [f"E{i}" for i in range(1, len(keys) + 1)]
    assert keys == expected_keys

    # Each key is present in ctx
    for k in keys:
        assert f"[{k}]" in ctx


def test_oversized_single_chunk_truncated_safely():
    """One oversized chunk is truncated with '[truncated]' marker and non-ASCII safe."""
    huge_text = "def hello():\n    return '🚀 Unicode test 🔥'\n" * 500
    chunk = {
        "chunk_id": "huge_1",
        "file_path": "src/huge.py",
        "start_line": 1,
        "end_line": 1000,
        "language": "python",
        "chunk_text": huge_text,
    }

    ctx, ev_map = build_evidence_context([chunk], max_evidence_chars=500)
    assert "E1" in ev_map
    assert "[truncated]" in ctx


def test_citation_validator_accepts_valid_and_rejects_unknown():
    """Citation validator keeps valid [E1] tag and strips unknown [E99]."""
    ev_map = {
        "E1": {"citation_id": "E1", "chunk_id": "c1", "file_path": "a.py"}
    }
    raw_answer = "Function foo in [E1] is unsafe, while [E99] does not exist."
    cleaned, citations = validate_citations(raw_answer, ev_map)

    assert "[E1]" in cleaned
    assert "[E99]" not in cleaned
    assert len(citations) == 1
    assert citations[0]["citation_id"] == "E1"
