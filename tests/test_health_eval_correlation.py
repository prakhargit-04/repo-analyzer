"""
Unit tests for health score correlation metrics (Spearman rho and Kendall tau).
"""
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_HEALTH = REPO_ROOT / "eval" / "health"
if str(EVAL_HEALTH) not in sys.path:
    sys.path.insert(0, str(EVAL_HEALTH))

from correlation import rank_data, spearman_rho, kendall_tau, evaluate_ratings


def test_rank_data_ties():
    # Elements: [10, 20, 20, 30]
    # Ranks: [1.0, 2.5, 2.5, 4.0]
    ranks = rank_data([10, 20, 20, 30])
    assert ranks == [1.0, 2.5, 2.5, 4.0]


def test_perfect_positive_correlation():
    x = [1, 2, 3, 4, 5]
    y = [10, 20, 30, 40, 50]
    assert spearman_rho(x, y) == pytest.approx(1.0)
    assert kendall_tau(x, y) == pytest.approx(1.0)


def test_perfect_negative_correlation():
    x = [1, 2, 3, 4, 5]
    y = [50, 40, 30, 20, 10]
    assert spearman_rho(x, y) == pytest.approx(-1.0)
    assert kendall_tau(x, y) == pytest.approx(-1.0)


def test_unvalidated_when_no_ratings(tmp_path):
    csv_file = tmp_path / "sheet.csv"
    csv_file.write_text("repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id\nhttps://example.com,abc,domain,,,\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is False
    assert "NOT VALIDATED: 0 of 1" in res["status"]
