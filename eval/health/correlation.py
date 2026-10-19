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
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


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


def evaluate_ratings(csv_path: str) -> dict[str, Any]:
    """Evaluates human ratings against pipeline scores."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_rows = len(rows)
    rated_rows = []
    for r in rows:
        val = r.get("human_rating_1_to_5", "").strip()
        if val:
            try:
                num = float(val)
                rated_rows.append((r, num))
            except ValueError:
                pass

    if not rated_rows:
        return {
            "validated": False,
            "status": f"NOT VALIDATED: 0 of {total_rows} ratings reviewed",
            "total_rows": total_rows,
            "reviewed_count": 0,
        }

    # If rated rows exist, extract scores and compute correlations
    # (Assuming algorithmic_score column or mock score present)
    human_scores = [rating for _, rating in rated_rows]
    pipeline_scores = [
        float(r.get("algorithmic_score", 50.0)) for r, _ in rated_rows
    ]

    rho = spearman_rho(human_scores, pipeline_scores)
    tau = kendall_tau(human_scores, pipeline_scores)

    return {
        "validated": True,
        "status": f"VALIDATED: {len(rated_rows)} of {total_rows} ratings reviewed",
        "total_rows": total_rows,
        "reviewed_count": len(rated_rows),
        "spearman_rho": round(rho, 4),
        "kendall_tau": round(tau, 4),
        "meets_preregistered_spearman": rho >= 0.60 and len(rated_rows) >= 15,
        "meets_preregistered_kendall": tau >= 0.80 and len(rated_rows) >= 15,
    }


def main():
    parser = argparse.ArgumentParser(description="Calculate Spearman and Kendall correlation on health ratings")
    parser.add_argument("csv_path", default="eval/health/rating_sheet.csv", nargs="?", help="Rating sheet CSV path")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    res = evaluate_ratings(args.csv_path)

    if not res["validated"]:
        print(res["status"])
        if args.json:
            print(json.dumps(res, indent=2))
        return

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"=== Health Score Empirical Correlation Results ===")
        print(f"Status: {res['status']}")
        print(f"Spearman rho: {res['spearman_rho']:.4f} (Threshold >= 0.60: {res['meets_preregistered_spearman']})")
        print(f"Kendall tau:  {res['kendall_tau']:.4f} (Threshold >= 0.80: {res['meets_preregistered_kendall']})")


if __name__ == "__main__":
    main()
