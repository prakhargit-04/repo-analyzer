"""
Offline unit tests for eval metric functions.
No network, no API keys, no LLM, no external services.
Collected by default (not marked live_ai).
"""
from __future__ import annotations

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.run_retrieval_eval import hit_at_k, recall_at_k, mrr, compute_metrics, lexical_score


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


def test_compute_metrics_difficulty_breakdown():
    results = [
        _make_result(["a.py"], ["a.py"], difficulty="lookup", top1_score=0.9),
        _make_result(["b.py"], ["b.py"], difficulty="explanation", top1_score=0.8),
    ]
    m = compute_metrics(results, k_values=[1])
    assert "mrr_lookup" in m
    assert "mrr_explanation" in m


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
