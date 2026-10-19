#!/usr/bin/env python3
"""
Graph Accuracy Metrics Calculator with Wilson Score 95% Confidence Intervals.

Reads an edge annotation CSV sheet and reports precision, recall (if reference set provided),
f1, and per-edge-type breakdown with rigorous Wilson 95% binomial confidence intervals.
If 0 labels are reviewed, it strictly outputs 'NOT VALIDATED: 0 of N labels reviewed'.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from typing import Any


def wilson_ci(k: int, n: int, z: float = 1.95996) -> tuple[float, float]:
    """Computes 95% Wilson score confidence interval for binomial proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + (z ** 2) / n
    center = (p + (z ** 2) / (2.0 * n)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / n) + ((z ** 2) / (4.0 * (n ** 2))))) / denom
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return (round(lower, 4), round(upper, 4))


def calculate_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Calculate accuracy metrics from annotation rows."""
    total_rows = len(rows)
    reviewed = [
        r for r in rows
        if r.get("label", "").strip().upper() in ("TP", "FP", "AMBIGUOUS", "FN")
    ]

    if not reviewed:
        return {
            "validated": False,
            "status": f"NOT VALIDATED: 0 of {total_rows} labels reviewed",
            "total_rows": total_rows,
            "reviewed_count": 0,
            "overall": None,
            "per_edge_type": {},
        }

    # Stratified breakdown
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in reviewed:
        etype = r.get("edge_type", "unknown")
        by_type[etype].append(r)

    def summarize_group(group_rows: list[dict[str, str]]) -> dict[str, Any]:
        tp = sum(1 for r in group_rows if r.get("label", "").strip().upper() == "TP")
        fp = sum(1 for r in group_rows if r.get("label", "").strip().upper() == "FP")
        ambig = sum(1 for r in group_rows if r.get("label", "").strip().upper() == "AMBIGUOUS")
        fn = sum(1 for r in group_rows if r.get("label", "").strip().upper() == "FN")

        valid_eval = tp + fp
        precision = tp / valid_eval if valid_eval > 0 else 0.0
        precision_conservative = tp / (valid_eval + ambig) if (valid_eval + ambig) > 0 else 0.0
        ci_low, ci_high = wilson_ci(tp, valid_eval)

        # Recall/F1 can only be calculated if ground-truth FN markers exist in the sample
        if (tp + fn) > 0 and fn > 0:
            recall = round(tp / (tp + fn), 4)
            f1 = round((2 * precision * recall) / (precision + recall), 4) if (precision and recall) else 0.0
        else:
            recall = None
            f1 = None

        return {
            "total_reviewed": len(group_rows),
            "tp": tp,
            "fp": fp,
            "ambiguous": ambig,
            "fn": fn,
            "evaluated_count": valid_eval,
            "precision": round(precision, 4),
            "precision_conservative": round(precision_conservative, 4),
            "precision_95ci": [ci_low, ci_high],
            "recall": recall,
            "f1": f1,
        }

    overall = summarize_group(reviewed)
    per_type = {etype: summarize_group(g_rows) for etype, g_rows in by_type.items()}

    # Only mark validated if all rows have been reviewed
    is_fully_reviewed = (len(reviewed) == total_rows and total_rows > 0)
    status_str = (
        f"VALIDATED: {len(reviewed)} of {total_rows} labels reviewed"
        if is_fully_reviewed
        else f"INCOMPLETE: {len(reviewed)} of {total_rows} labels reviewed (requires {total_rows}/{total_rows})"
    )

    return {
        "validated": is_fully_reviewed,
        "status": status_str,
        "total_rows": total_rows,
        "reviewed_count": len(reviewed),
        "overall": overall,
        "per_edge_type": per_type,
    }


def load_csv(csv_path: str) -> list[dict[str, str]]:
    """Loads CSV rows as dicts."""
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def main():
    parser = argparse.ArgumentParser(description="Compute accuracy metrics and Wilson 95% CIs on graph annotation sheet")
    parser.add_argument("csv_path", help="Path to annotation CSV")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    rows = load_csv(args.csv_path)
    res = calculate_metrics(rows)

    if not res["validated"]:
        print(res["status"])
        if args.json:
            print(json.dumps(res, indent=2))
        return

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print("=== Graph Edge Accuracy Metrics ===")
        print(f"Status: {res['status']}")
        ov = res["overall"]
        print(f"Precision: {ov['precision'] * 100:.2f}%  (95% CI: [{ov['precision_95ci'][0]*100:.1f}%, {ov['precision_95ci'][1]*100:.1f}%])")
        print(f"Counts: TP={ov['tp']}, FP={ov['fp']}, AMBIGUOUS={ov['ambiguous']}")
        print("\nBreakdown by Edge Type:")
        for etype, data in res["per_edge_type"].items():
            print(f"  - {etype:<12}: Precision={data['precision']*100:5.1f}% (95% CI [{data['precision_95ci'][0]*100:.1f}%, {data['precision_95ci'][1]*100:.1f}%])  (TP={data['tp']}, FP={data['fp']}, AMBIG={data['ambiguous']})")


if __name__ == "__main__":
    main()
