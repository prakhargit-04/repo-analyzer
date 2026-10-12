"""
Offline unit tests for eval metric functions, score extraction, and safety gates.
No network, no API keys, no LLM, no external services.
Collected by default (not marked live_ai).
"""
from __future__ import annotations

import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.run_retrieval_eval import (
    hit_at_k,
    recall_at_k,
    mrr,
    compute_metrics,
    lexical_score,
    extract_top1_score,
    _check_questions_all_reviewed,
    _build_corpus,
    write_markdown_summary,
)


# ---------------------------------------------------------------------------
# hit_at_k
# ---------------------------------------------------------------------------

def test_hit_at_k_found_at_rank_1():
    assert hit_at_k(["a.py", "b.py", "c.py"], ["a.py"], k=1) == 1


def test_hit_at_k_found_at_rank_3_but_k_is_2():
    assert hit_at_k(["x.py", "y.py", "a.py"], ["a.py"], k=2) == 0


def test_hit_at_k_found_at_rank_3_and_k_is_3():
    assert hit_at_k(["x.py", "y.py", "a.py"], ["a.py"], k=3) == 1


def test_hit_at_k_empty_retrieved():
    assert hit_at_k([], ["a.py"], k=5) == 0


def test_hit_at_k_empty_expected():
    assert hit_at_k(["a.py"], [], k=5) == 0


# ---------------------------------------------------------------------------
# recall_at_k
# ---------------------------------------------------------------------------

def test_recall_at_k_full():
    assert recall_at_k(["a.py", "b.py"], ["a.py", "b.py"], k=2) == 1.0


def test_recall_at_k_partial():
    assert recall_at_k(["a.py", "c.py"], ["a.py", "b.py"], k=2) == 0.5


def test_recall_at_k_none():
    assert recall_at_k(["x.py", "y.py"], ["a.py", "b.py"], k=5) == 0.0


def test_recall_at_k_empty_expected():
    assert recall_at_k(["a.py"], [], k=5) == 0.0


def test_recall_at_k_k_limits_window():
    # b.py is at rank 3 but k=2
    assert recall_at_k(["a.py", "x.py", "b.py"], ["a.py", "b.py"], k=2) == 0.5


# ---------------------------------------------------------------------------
# mrr
# ---------------------------------------------------------------------------

def test_mrr_first_rank():
    assert mrr(["a.py", "b.py"], ["a.py"]) == pytest.approx(1.0)


def test_mrr_second_rank():
    assert mrr(["x.py", "a.py"], ["a.py"]) == pytest.approx(0.5)


def test_mrr_third_rank():
    assert mrr(["x.py", "y.py", "a.py"], ["a.py"]) == pytest.approx(1 / 3)


def test_mrr_not_found():
    assert mrr(["x.py", "y.py"], ["a.py"]) == 0.0


def test_mrr_multiple_expected_first_match():
    # a.py is at rank 2, b.py is at rank 1
    assert mrr(["b.py", "a.py"], ["a.py", "b.py"]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

def _make_result(retrieved, expected, unanswerable=False, latency_ms=10.0,
                 top1_score=None, difficulty="lookup", paraphrase=False):
    return {
        "retrieved_files": retrieved,
        "expected_files": expected,
        "unanswerable": unanswerable,
        "latency_ms": latency_ms,
        "top1_score": top1_score if top1_score is not None else (0.9 if retrieved else None),
        "difficulty": difficulty,
        "paraphrase": paraphrase,
    }


def test_compute_metrics_basic():
    results = [
        _make_result(["a.py", "b.py"], ["a.py"], top1_score=0.9),
        _make_result(["x.py"], ["a.py"], top1_score=0.3),
    ]
    m = compute_metrics(results, k_values=[1, 3])
    assert m["answerable_count"] == 2
    assert 0 <= m["recall@1"] <= 1.0
    assert 0 <= m["mrr"] <= 1.0


def test_compute_metrics_empty_answerable():
    results = [_make_result([], [], unanswerable=True)]
    m = compute_metrics(results, k_values=[1, 5])
    assert m["answerable_count"] == 0


def test_compute_metrics_unanswerable_tracked_separately():
    results = [
        _make_result(["a.py"], ["a.py"], top1_score=0.9),
        _make_result(["z.py"], [], unanswerable=True, top1_score=0.2),
    ]
    m = compute_metrics(results, k_values=[1])
    assert m.get("unanswerable_count") == 1
    assert "unanswerable_top1_score_mean" in m
    assert m["unanswerable_top1_score_mean"] == pytest.approx(0.2)
    assert m["unanswerable_top1_score_min"] == pytest.approx(0.2)
    assert m["unanswerable_top1_score_max"] == pytest.approx(0.2)


def test_compute_metrics_hit_miss_top1_breakdown():
    results = [
        _make_result(["a.py"], ["a.py"], top1_score=0.95),  # Hit
        _make_result(["wrong.py"], ["a.py"], top1_score=0.40),  # Miss
    ]
    m = compute_metrics(results, k_values=[1])
    assert m["top1_score_hit_mean"] == pytest.approx(0.95)
    assert m["top1_score_miss_mean"] == pytest.approx(0.40)


def test_compute_metrics_difficulty_breakdown():
    results = [
        _make_result(["a.py"], ["a.py"], difficulty="lookup", top1_score=0.9),
        _make_result(["b.py"], ["b.py"], difficulty="explanation", top1_score=0.8),
    ]
    m = compute_metrics(results, k_values=[1])
    assert "mrr_lookup" in m
    assert "mrr_explanation" in m


# ---------------------------------------------------------------------------
# extract_top1_score Helper Tests
# ---------------------------------------------------------------------------

def test_extract_top1_score_valid_score():
    sem_chunks = [{"chunk_id": "c1", "score": 0.8542}]
    assert extract_top1_score(sem_chunks) == pytest.approx(0.8542)


def test_extract_top1_score_similarity_score_fallback():
    sem_chunks = [{"chunk_id": "c1", "similarity_score": 0.7610}]
    assert extract_top1_score(sem_chunks) == pytest.approx(0.7610)


def test_extract_top1_score_empty_result():
    assert extract_top1_score([]) is None
    assert extract_top1_score(None) is None


def test_extract_top1_score_unavailable_score():
    sem_chunks = [{"chunk_id": "c1"}]
    assert extract_top1_score(sem_chunks) is None
    sem_chunks_none = [{"chunk_id": "c1", "score": None}]
    assert extract_top1_score(sem_chunks_none) is None


def test_extract_top1_score_malformed_value_raises_value_error():
    sem_chunks = [{"chunk_id": "c1", "score": "invalid_string"}]
    with pytest.raises(ValueError, match="Invalid score type"):
        extract_top1_score(sem_chunks)


# ---------------------------------------------------------------------------
# Markdown Summary Writer Tests
# ---------------------------------------------------------------------------

def test_write_markdown_summary_includes_p95_and_per_repo():
    result = {
        "embedding_provider": "test",
        "smoke": True,
        "k_values": [1, 5],
        "semantic": {
            "answerable_count": 2,
            "unanswerable_count": 0,
            "recall@1": 1.0,
            "hit@1": 1.0,
            "recall@5": 1.0,
            "hit@5": 1.0,
            "mrr": 1.0,
            "latency_median_ms": 12.3,
            "latency_p95_ms": 15.7,
        },
        "lexical_baseline": {
            "recall@1": 0.5,
            "recall@5": 1.0,
            "mrr": 0.5,
            "latency_median_ms": 1.1,
            "latency_p95_ms": 1.9,
        },
        "per_repository": {
            "repo_a": {
                "semantic": {"answerable_count": 2, "mrr": 1.0, "recall@1": 1.0, "recall@5": 1.0},
                "lexical_baseline": {"answerable_count": 2, "mrr": 0.5, "recall@1": 0.5, "recall@5": 1.0},
            }
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "summary.md")
        write_markdown_summary(result, out_path)
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "| Latency p95 ms | 15.7 |" in content
        assert "## Per-Repository Breakdown" in content
        assert "Repository: `repo_a`" in content


# ---------------------------------------------------------------------------
# Question Review Safety Gate (Fails Closed)
# ---------------------------------------------------------------------------

def test_safety_gate_question_review_reviewed():
    questions = [
        {"id": "q1", "status": "reviewed"},
        {"id": "q2", "status": "reviewed"},
    ]
    # Must not raise RuntimeError
    _check_questions_all_reviewed(questions)


def test_safety_gate_question_review_draft():
    questions = [
        {"id": "q1", "status": "reviewed"},
        {"id": "q2", "status": "draft"},
    ]
    with pytest.raises(RuntimeError, match="SAFETY GATE TRIGGERED"):
        _check_questions_all_reviewed(questions)


def test_safety_gate_question_review_missing_status():
    questions = [
        {"id": "q1", "status": "reviewed"},
        {"id": "q2"},  # Missing status field -> fails closed
    ]
    with pytest.raises(RuntimeError, match="SAFETY GATE TRIGGERED"):
        _check_questions_all_reviewed(questions)


# ---------------------------------------------------------------------------
# Embedding Generation Safety Gate
# ---------------------------------------------------------------------------

def test_embedding_stage_safety_gate():
    fake_pipe = {
        "parse_repository": lambda p: [],
        "generate_repository_chunks": lambda p, r, commit_sha=None: [{"chunk_id": "c1"}],
        "get_embedding_provider": lambda: None,
        "generate_source_embeddings": lambda chunks, repo_url, commit_sha, provider: (
            [], {"status": "failed", "error": "Provider connection refused"}
        ),
    }

    with pytest.raises(RuntimeError, match="SAFETY GATE TRIGGERED: Embedding generation failed"):
        _build_corpus(
            local_path="/tmp/fake",
            commit_sha="abc123",
            pipe=fake_pipe,
            db_url="sqlite:///:memory:",
            repo_url="https://github.com/fake/repo",
        )


def test_embedding_stage_mismatched_count_safety_gate():
    fake_pipe = {
        "parse_repository": lambda p: [],
        "generate_repository_chunks": lambda p, r, commit_sha=None: [{"chunk_id": "c1"}, {"chunk_id": "c2"}],
        "get_embedding_provider": lambda: None,
        "generate_source_embeddings": lambda chunks, repo_url, commit_sha, provider: (
            [{"source_chunk_id": "c1"}], {"status": "completed"}  # 1 embedding for 2 chunks!
        ),
    }

    with pytest.raises(RuntimeError, match="SAFETY GATE TRIGGERED: Embedding generation failed"):
        _build_corpus(
            local_path="/tmp/fake",
            commit_sha="abc123",
            pipe=fake_pipe,
            db_url="sqlite:///:memory:",
            repo_url="https://github.com/fake/repo",
        )


# ---------------------------------------------------------------------------
# lexical_score
# ---------------------------------------------------------------------------

def test_lexical_score_exact_match():
    assert lexical_score("add function", "def add function here") == pytest.approx(1.0)


def test_lexical_score_no_overlap():
    assert lexical_score("hello world", "foo bar baz") == pytest.approx(0.0)


def test_lexical_score_partial():
    score = lexical_score("add numbers", "def add two values")
    assert 0 < score < 1.0


def test_lexical_score_empty_query():
    assert lexical_score("", "def add function") == pytest.approx(0.0)
