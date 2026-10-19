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


def test_deterministic_join_valid_and_blind(tmp_path):
    # Tests complete blind workflow: reviewer sheet has ZERO algorithmic scores.
    # Algorithmic scores are exported separately and joined deterministically.
    ratings_lines = ["repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id"]
    scores_lines = ["repo_url,commit_sha,algorithmic_score"]

    for i in range(15):
        rating = (i % 5) + 1
        score = rating * 18.0 + 8.0
        ratings_lines.append(f"https://example.com/r{i:02d},sha{i:02d},domain,{rating},blind note,evaluator_1")
        scores_lines.append(f"https://example.com/r{i:02d},sha{i:02d},{score:.2f}")

    ratings_csv = tmp_path / "blind_ratings.csv"
    scores_csv = tmp_path / "separate_scores.csv"
    ratings_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    scores_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    # Confirm reviewer CSV has no algorithmic_score column
    with open(ratings_csv, "r", encoding="utf-8") as f:
        header = f.readline()
        assert "algorithmic_score" not in header

    res = evaluate_ratings(str(ratings_csv), scores_csv_path=str(scores_csv))
    assert res["validated"] is True
    assert res["valid_paired_count"] == 15
    assert res["excluded_count"] == 0
    assert res["spearman_rho"] > 0.8
    assert res["kendall_tau"] > 0.8


def test_join_rejects_duplicate_keys_in_ratings(tmp_path):
    ratings_lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,4,note,eval1",
        "https://example.com/r1,sha1,domain,5,note,eval1",  # duplicate
    ]
    scores_lines = [
        "repo_url,commit_sha,algorithmic_score",
        "https://example.com/r1,sha1,85.0",
    ]
    r_csv = tmp_path / "ratings_dup.csv"
    s_csv = tmp_path / "scores.csv"
    r_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    s_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate key in ratings CSV"):
        evaluate_ratings(str(r_csv), scores_csv_path=str(s_csv))


def test_join_rejects_duplicate_keys_in_scores(tmp_path):
    ratings_lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,4,note,eval1",
    ]
    scores_lines = [
        "repo_url,commit_sha,algorithmic_score",
        "https://example.com/r1,sha1,85.0",
        "https://example.com/r1,sha1,90.0",  # duplicate
    ]
    r_csv = tmp_path / "ratings.csv"
    s_csv = tmp_path / "scores_dup.csv"
    r_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    s_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate key in scores CSV"):
        evaluate_ratings(str(r_csv), scores_csv_path=str(s_csv))


def test_join_rejects_mismatched_commit_sha(tmp_path):
    ratings_lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id",
        "https://example.com/r1,sha_pinned_111,domain,4,note,eval1",
    ]
    scores_lines = [
        "repo_url,commit_sha,algorithmic_score",
        "https://example.com/r1,sha_different_222,85.0",  # mismatched sha
    ]
    r_csv = tmp_path / "ratings.csv"
    s_csv = tmp_path / "scores_mismatch.csv"
    r_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    s_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Mismatched commit SHA"):
        evaluate_ratings(str(r_csv), scores_csv_path=str(s_csv))


def test_join_rejects_unmatched_rows(tmp_path):
    ratings_lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,4,note,eval1",
        "https://example.com/r2,sha2,domain,5,note,eval1",
    ]
    scores_lines = [
        "repo_url,commit_sha,algorithmic_score",
        "https://example.com/r1,sha1,85.0",
        # r2 missing in scores
    ]
    r_csv = tmp_path / "ratings.csv"
    s_csv = tmp_path / "scores_missing.csv"
    r_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    s_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unmatched rows between ratings and scores"):
        evaluate_ratings(str(r_csv), scores_csv_path=str(s_csv))


def test_join_rejects_invalid_score(tmp_path):
    ratings_lines = [
        "repo_url,commit_sha,domain,human_rating_1_to_5,notes,evaluator_id",
        "https://example.com/r1,sha1,domain,4,note,eval1",
    ]
    scores_lines = [
        "repo_url,commit_sha,algorithmic_score",
        "https://example.com/r1,sha1,105.0",  # > 100
    ]
    r_csv = tmp_path / "ratings.csv"
    s_csv = tmp_path / "scores_invalid.csv"
    r_csv.write_text("\n".join(ratings_lines) + "\n", encoding="utf-8")
    s_csv.write_text("\n".join(scores_lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="out of range"):
        evaluate_ratings(str(r_csv), scores_csv_path=str(s_csv))

