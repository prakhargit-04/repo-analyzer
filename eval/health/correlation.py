#!/usr/bin/env python3
"""
Health Score Empirical Correlation Script (Session 25 Part F).

Calculates Spearman rank correlation (rho) and Kendall's tau between
human engineer ratings and algorithmic health scores.
If 0 ratings are filled, outputs 'NOT VALIDATED: 0 of N ratings reviewed'.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from typing import Any


def rank_data(a: list[float]) -> list[float]:
    """Assign fractional ranks to elements, averaging ties."""
    n = len(a)
    sorted_indices = sorted(range(n), key=lambda i: a[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and a[sorted_indices[j]] == a[sorted_indices[j + 1]]:
            j += 1
        avg_rank = (i + j + 2) / 2.0  # 1-based rank average
        for k in range(i, j + 1):
            ranks[sorted_indices[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_rho(x: list[float], y: list[float]) -> float:
    """Computes Spearman rank correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0.0
    rx = rank_data(x)
    ry = rank_data(y)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    var_x = sum((rx[i] - mean_rx) ** 2 for i in range(n))
    var_y = sum((ry[i] - mean_ry) ** 2 for i in range(n))
    if var_x == 0 or var_y == 0:
        return 0.0
    return cov / math.sqrt(var_x * var_y)


def kendall_tau(x: list[float], y: list[float]) -> float:
    """Computes Kendall's tau-b rank correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0.0
    concordant = 0
    discordant = 0
    tie_x = 0
    tie_y = 0

    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx == 0 and dy == 0:
                continue
            elif dx == 0:
                tie_x += 1
            elif dy == 0:
                tie_y += 1
            elif (dx > 0 and dy > 0) or (dx < 0 and dy < 0):
                concordant += 1
            else:
                discordant += 1

    denom = math.sqrt((concordant + discordant + tie_x) * (concordant + discordant + tie_y))
    if denom == 0:
        return 0.0
    return (concordant - discordant) / denom


def join_ratings_and_scores(
    ratings_csv_path: str,
    scores_csv_path: str,
) -> list[dict[str, Any]]:
    """
    Deterministically joins blind human ratings with algorithmic scores.
    Keyed strictly by (repo_url, commit_sha).

    Integrity checks:
    - Rejects duplicate keys in either ratings or scores.
    - Rejects mismatched commit SHAs for the same repository URL.
    - Rejects unmatched rows (keys present in one file but not the other).
    - Rejects invalid scores (missing, blank, non-numeric, or not in [0.0, 100.0]).
    """
    with open(ratings_csv_path, "r", encoding="utf-8") as f:
        ratings_reader = csv.DictReader(f)
        ratings_rows = list(ratings_reader)

    ratings_map: dict[tuple[str, str], dict[str, Any]] = {}
    ratings_url_to_sha: dict[str, str] = {}
    for r in ratings_rows:
        url = r.get("repo_url", "").strip()
        sha = r.get("commit_sha", "").strip()
        if not url or not sha:
            raise ValueError(f"Rating row missing repo_url or commit_sha: {r}")
        key = (url, sha)
        if key in ratings_map:
            raise ValueError(f"Duplicate key in ratings CSV: {key}")
        if url in ratings_url_to_sha and ratings_url_to_sha[url] != sha:
            raise ValueError(f"Duplicate repository URL with conflicting commit SHA in ratings CSV: {url}")
        ratings_map[key] = r
        ratings_url_to_sha[url] = sha

    with open(scores_csv_path, "r", encoding="utf-8") as f:
        scores_reader = csv.DictReader(f)
        scores_rows = list(scores_reader)

    scores_map: dict[tuple[str, str], float] = {}
    scores_url_to_sha: dict[str, str] = {}
    for r in scores_rows:
        url = r.get("repo_url", "").strip()
        sha = r.get("commit_sha", "").strip()
        if not url or not sha:
            raise ValueError(f"Score row missing repo_url or commit_sha: {r}")
        key = (url, sha)
        if key in scores_map:
            raise ValueError(f"Duplicate key in scores CSV: {key}")
        if url in scores_url_to_sha and scores_url_to_sha[url] != sha:
            raise ValueError(f"Duplicate repository URL with conflicting commit SHA in scores CSV: {url}")

        if url in ratings_url_to_sha and ratings_url_to_sha[url] != sha:
            raise ValueError(
                f"Mismatched commit SHA for repository '{url}': "
                f"ratings has '{ratings_url_to_sha[url]}' but scores has '{sha}'"
            )

        raw_score = r.get("algorithmic_score", "").strip()
        if not raw_score:
            raise ValueError(f"Invalid algorithmic score for {key}: score is missing or blank")
        try:
            score_val = float(raw_score)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid algorithmic score for {key}: '{raw_score}' is not numeric") from exc
        if not (0.0 <= score_val <= 100.0):
            raise ValueError(f"Invalid algorithmic score for {key}: {score_val} is out of range [0.0, 100.0]")

        scores_map[key] = score_val
        scores_url_to_sha[url] = sha

    # Check unmatched rows
    ratings_keys = set(ratings_map.keys())
    scores_keys = set(scores_map.keys())
    unmatched_in_ratings = ratings_keys - scores_keys
    unmatched_in_scores = scores_keys - ratings_keys
    if unmatched_in_ratings or unmatched_in_scores:
        raise ValueError(
            f"Unmatched rows between ratings and scores: "
            f"in ratings but not scores: {unmatched_in_ratings}; "
            f"in scores but not ratings: {unmatched_in_scores}"
        )

    # Deterministic output sorted by (url, sha)
    joined_rows = []
    for key in sorted(ratings_keys):
        merged = dict(ratings_map[key])
        merged["algorithmic_score"] = str(scores_map[key])
        joined_rows.append(merged)

    return joined_rows


def evaluate_ratings(
    csv_path: str,
    scores_csv_path: str | None = None,
) -> dict[str, Any]:
    """
    Evaluates human ratings against pipeline scores.

    Integrity Invariants:
    1. Human rating must be a valid float between 1.0 and 5.0. Blank indicates unreviewed.
    2. Algorithmic score must be a valid float between 0.0 and 100.0. Missing/blank scores
       are explicitly EXCLUDED (never defaulted to 50.0 or any other fallback).
    3. Rows with non-numeric, invalid, or out-of-range ratings/scores are excluded, and
       the excluded count is reported.
    4. Validation status requires >= 15 valid paired ratings across the full panel.
    5. Supports scores_csv_path for deterministic post-rating join keeping reviewer CSV blind.
    """
    if scores_csv_path:
        rows = join_ratings_and_scores(csv_path, scores_csv_path)
    else:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

    total_rows = len(rows)
    valid_paired_rows: list[tuple[float, float]] = []
    excluded_count = 0
    unreviewed_count = 0

    for r in rows:
        val_h = r.get("human_rating_1_to_5", "").strip() if r.get("human_rating_1_to_5") else ""
        val_a = r.get("algorithmic_score", "").strip() if r.get("algorithmic_score") else ""

        # Unreviewed row: human rating is blank
        if not val_h:
            unreviewed_count += 1
            continue

        # Parse human rating: must be float 1.0 .. 5.0
        try:
            h_score = float(val_h)
            if not (1.0 <= h_score <= 5.0):
                excluded_count += 1
                continue
        except (ValueError, TypeError):
            excluded_count += 1
            continue

        # Parse algorithmic score: must be present and float 0.0 .. 100.0 (NO 50.0 fallback!)
        if not val_a:
            excluded_count += 1
            continue
        try:
            a_score = float(val_a)
            if not (0.0 <= a_score <= 100.0):
                excluded_count += 1
                continue
        except (ValueError, TypeError):
            excluded_count += 1
            continue

        valid_paired_rows.append((h_score, a_score))

    valid_paired_count = len(valid_paired_rows)

    if valid_paired_count == 0:
        return {
            "validated": False,
            "status": f"NOT VALIDATED: 0 of {total_rows} ratings reviewed ({unreviewed_count} unreviewed, {excluded_count} excluded)",
            "total_rows": total_rows,
            "valid_paired_count": 0,
            "reviewed_count": 0,
            "unreviewed_count": unreviewed_count,
            "excluded_count": excluded_count,
            "spearman_rho": None,
            "kendall_tau": None,
            "meets_preregistered_spearman": False,
            "meets_preregistered_kendall": False,
        }

    human_scores = [h for h, _ in valid_paired_rows]
    pipeline_scores = [a for _, a in valid_paired_rows]

    rho = spearman_rho(human_scores, pipeline_scores) if valid_paired_count >= 2 else None
    tau = kendall_tau(human_scores, pipeline_scores) if valid_paired_count >= 2 else None

    # Pre-registered protocol requires >= 15 valid paired ratings across the candidate panel
    is_fully_validated = (valid_paired_count >= 15 and valid_paired_count == total_rows and excluded_count == 0)
    if valid_paired_count < 15:
        status_str = f"INCOMPLETE: {valid_paired_count} valid paired ratings (requires >= 15 ratings for empirical validation; {excluded_count} excluded, {unreviewed_count} unreviewed)"
    elif valid_paired_count < total_rows:
        status_str = f"INCOMPLETE: {valid_paired_count} of {total_rows} valid paired ratings ({excluded_count} excluded, {unreviewed_count} unreviewed)"
    else:
        status_str = f"VALIDATED: {valid_paired_count} of {total_rows} valid ratings reviewed"

    return {
        "validated": is_fully_validated,
        "status": status_str,
        "total_rows": total_rows,
        "valid_paired_count": valid_paired_count,
        "reviewed_count": valid_paired_count,
        "unreviewed_count": unreviewed_count,
        "excluded_count": excluded_count,
        "spearman_rho": round(rho, 4) if rho is not None else None,
        "kendall_tau": round(tau, 4) if tau is not None else None,
        "meets_preregistered_spearman": bool(rho is not None and rho >= 0.60 and valid_paired_count >= 15),
        "meets_preregistered_kendall": bool(tau is not None and tau >= 0.80 and valid_paired_count >= 15),
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate Spearman and Kendall correlation on health ratings")
    parser.add_argument("csv_path", default="eval/health/rating_sheet.csv", nargs="?", help="Rating sheet CSV path")
    parser.add_argument("--scores", default=None, help="Path to separate algorithmic scores CSV for deterministic join")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    res = evaluate_ratings(args.csv_path, scores_csv_path=args.scores)

    if not res["validated"]:
        print(res["status"])
        if args.json:
            print(json.dumps(res, indent=2))
        return

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print("=== Health Score Empirical Correlation Results ===")
        print(f"Status: {res['status']}")
        print(f"Spearman rho: {res['spearman_rho']:.4f} (Threshold >= 0.60: {res['meets_preregistered_spearman']})")
        print(f"Kendall tau:  {res['kendall_tau']:.4f} (Threshold >= 0.80: {res['meets_preregistered_kendall']})")


if __name__ == "__main__":
    main()
