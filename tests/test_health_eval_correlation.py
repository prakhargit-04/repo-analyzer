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


def test_incomplete_when_under_15_ratings(tmp_path):
    lines = ["repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id"]
    for i in range(5):
        lines.append(f"https://example.com/r{i},abc{i},domain,{i+1},{(i+1)*20},note,eval1")
    csv_file = tmp_path / "sheet5.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is False
    assert "INCOMPLETE: 5 valid paired ratings" in res["status"]
    assert "requires >= 15" in res["status"]


def test_validated_when_15_ratings(tmp_path):
    lines = ["repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id"]
    for i in range(15):
        rating = (i % 5) + 1
        score = rating * 18 + 5
        lines.append(f"https://example.com/r{i},abc{i},domain,{rating},{score},note,eval1")
    csv_file = tmp_path / "sheet15.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is True
    assert "VALIDATED: 15 of 15" in res["status"]
    assert res["valid_paired_count"] == 15
    assert res["excluded_count"] == 0
    assert res["spearman_rho"] > 0.8
    assert res["kendall_tau"] > 0.8
    assert res["meets_preregistered_spearman"] is True
    assert res["meets_preregistered_kendall"] is True


def test_missing_and_blank_algorithmic_score_excluded(tmp_path):
    # Tests that missing or blank algorithmic score is NEVER defaulted to 50.0
    lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,4,,no algorithmic score,eval1",
        "https://example.com/r2,sha2,domain,3,  ,blank algorithmic score,eval1",
        "https://example.com/r3,sha3,domain,5,85.0,valid,eval1",
    ]
    csv_file = tmp_path / "missing_scores.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is False
    assert res["valid_paired_count"] == 1
    assert res["excluded_count"] == 2
    assert "INCOMPLETE: 1 valid paired ratings" in res["status"]


def test_invalid_human_ratings_excluded(tmp_path):
    # Non-numeric, out-of-range (< 1 or > 5) human ratings must be excluded
    lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,0,80.0,too low,eval1",
        "https://example.com/r2,sha2,domain,6,80.0,too high,eval1",
        "https://example.com/r3,sha3,domain,not-a-number,80.0,non-numeric,eval1",
        "https://example.com/r4,sha4,domain,-2,80.0,negative,eval1",
        "https://example.com/r5,sha5,domain,4,80.0,valid,eval1",
    ]
    csv_file = tmp_path / "invalid_ratings.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is False
    assert res["valid_paired_count"] == 1
    assert res["excluded_count"] == 4


def test_constant_scores_zero_variance(tmp_path):
    # When algorithmic score is constant across all 15 repositories,
    # variance is zero. Must return correlation 0.0 without division by zero.
    lines = ["repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id"]
    for i in range(15):
        rating = (i % 5) + 1
        lines.append(f"https://example.com/r{i},abc{i},domain,{rating},75.0,constant score,eval1")
    csv_file = tmp_path / "constant_scores.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["valid_paired_count"] == 15
    assert res["spearman_rho"] == 0.0
    assert res["kendall_tau"] == 0.0
    assert res["meets_preregistered_spearman"] is False
    assert res["meets_preregistered_kendall"] is False


def test_insufficient_samples_under_15(tmp_path):
    # 14 valid ratings (1 short of 15) must not report validation
    lines = ["repo_url,commit_sha,domain,human_rating_1_to_5,algorithmic_score,notes,evaluator_id"]
    for i in range(14):
        rating = (i % 5) + 1
        score = rating * 15 + 10
        lines.append(f"https://example.com/r{i},abc{i},domain,{rating},{score},note,eval1")
    csv_file = tmp_path / "sheet14.csv"
    csv_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = evaluate_ratings(str(csv_file))
    assert res["validated"] is False
    assert res["valid_paired_count"] == 14
    assert res["meets_preregistered_spearman"] is False
    assert res["meets_preregistered_kendall"] is False
    assert "requires >= 15" in res["status"]
