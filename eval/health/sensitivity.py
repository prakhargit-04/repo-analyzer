#!/usr/bin/env python3
"""
Health Score Sensitivity Analysis Script (Session 25 Part F).

Perturbs each health score component weight by +/-20% (with renormalization)
and measures composite score drift to identify the most volatile weights.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from health_score import compute_health_score, DEFAULT_WEIGHTS_V2


def run_sensitivity_analysis(
    subscores: dict[str, float],
    base_weights: dict[str, float] | None = None,
    perturbation: float = 0.20,
) -> dict[str, Any]:
    """
    Simulates sensitivity of composite score to +/- perturbation in individual component weights.
    """
    weights = dict(base_weights or DEFAULT_WEIGHTS_V2)

    # Synthetic analysis dict to feed compute_health_score
    def make_mock_analysis(m: float, c: float, s: float, d: float) -> dict[str, Any]:
        return {
            "maintainability": {"status": "success", "maintainability_index": m, "results": []},
            "complexity": {"status": "success", "results": [{"rank": "A", "cyclomatic_complexity": 2}]},
            "security": {
                "bandit": {"status": "success", "results": []},
                "semgrep": {"status": "success", "results": []},
                "gitleaks": {"status": "success", "results": []},
            },
            "dependencies": {"status": "success", "results": []},
        }

    # Baseline calculation with standard weights
    # Direct formula calculation consistent with compute_health_score
    base_total = sum(weights[k] for k in subscores if k in weights)
    base_score = sum(subscores[k] * (weights[k] / base_total) for k in subscores if k in weights)

    results: dict[str, Any] = {}
    for comp in weights:
        drifts = []
        for direction, delta in [("decrease (-20%)", -perturbation), ("increase (+20%)", perturbation)]:
            perturbed_weights = dict(weights)
            perturbed_weights[comp] = max(0.01, weights[comp] * (1.0 + delta))

            # Renormalize
            norm_total = sum(perturbed_weights[k] for k in subscores if k in perturbed_weights)
            perturbed_score = sum(
                subscores[k] * (perturbed_weights[k] / norm_total)
                for k in subscores if k in perturbed_weights
            )

            drift = abs(perturbed_score - base_score)
            drifts.append({
                "direction": direction,
                "perturbed_weight": round(perturbed_weights[comp], 4),
                "perturbed_score": round(perturbed_score, 2),
                "drift": round(drift, 2),
            })

        max_drift = max(d["drift"] for d in drifts)
        results[comp] = {
            "base_weight": weights[comp],
            "max_drift": max_drift,
            "perturbations": drifts,
        }

    # Rank by max drift descending (highest volatility first)
    ranked = sorted(results.items(), key=lambda x: x[1]["max_drift"], reverse=True)

    return {
        "base_score": round(base_score, 2),
        "subscores": subscores,
        "perturbation_percent": perturbation * 100,
        "ranked_volatility": [
            {
                "component": comp,
                "base_weight": data["base_weight"],
                "max_drift": data["max_drift"],
                "perturbations": data["perturbations"],
            }
            for comp, data in ranked
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze health score sensitivity to weight perturbations")
    parser.add_argument("--maintainability", type=float, default=95.0, help="Maintainability subscore (0-100)")
    parser.add_argument("--complexity", type=float, default=85.0, help="Complexity subscore (0-100)")
    parser.add_argument("--security", type=float, default=70.0, help="Security subscore (0-100)")
    parser.add_argument("--dependencies", type=float, default=60.0, help="Dependencies subscore (0-100)")
    parser.add_argument("--perturbation", type=float, default=0.20, help="Perturbation fraction (default: 0.20 for +/-20%)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    subscores = {
        "maintainability": args.maintainability,
        "complexity": args.complexity,
        "security": args.security,
        "dependencies": args.dependencies,
    }

    report = run_sensitivity_analysis(subscores, perturbation=args.perturbation)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"=== Health Score Weight Sensitivity Analysis ===")
        print(f"Base Composite Score: {report['base_score']}")
        print(f"Subscores: {subscores}")
        print(f"Perturbation: +/-{report['perturbation_percent']:.0f}%\n")
        print(f"{'Component':<18} {'Base Weight':<14} {'Max Drift':<12} {'Volatility Ranking'}")
        print("-" * 65)
        for rank, item in enumerate(report["ranked_volatility"], 1):
            print(f"{item['component']:<18} {item['base_weight']:<14.2f} {item['max_drift']:<12.2f} #{rank}")
        print("\nConclusion: The most volatile weights are those with the highest distance from other subscores.")


if __name__ == "__main__":
    main()
