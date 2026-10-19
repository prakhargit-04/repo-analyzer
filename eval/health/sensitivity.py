#!/usr/bin/env python3
"""
Health Score Sensitivity Analysis Script (Session 25 Part F).

Perturbs each health score component weight by +/-20% (with renormalization)
and measures composite score drift to identify the most volatile weights.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from health_score import DEFAULT_WEIGHTS_V2


CANONICAL_V2_COMPONENTS = {
    "complexity": 85.0,
    "maintainability": 95.0,
    "security": 70.0,
    "sast": 80.0,
    "secrets": 90.0,
    "vulnerabilities": 75.0,
}


def run_sensitivity_analysis(
    subscores: dict[str, float] | None = None,
    base_weights: dict[str, float] | None = None,
    perturbation: float = 0.20,
) -> dict[str, Any]:
    """
    Simulates sensitivity of composite score to +/- perturbation in individual component weights.
    Supports all 6 Health Score v2 components.
    """
    weights = dict(base_weights or DEFAULT_WEIGHTS_V2)
    scores = dict(subscores or CANONICAL_V2_COMPONENTS)

    # Active components present in both weights and subscores
    active_keys = [k for k in weights if k in scores]
    if not active_keys:
        raise ValueError("No matching components between weights and subscores")

    # Baseline calculation with standard weights
    base_total = sum(weights[k] for k in active_keys)
    base_score = sum(scores[k] * (weights[k] / base_total) for k in active_keys)

    results: dict[str, Any] = {}
    for comp in active_keys:
        drifts = []
        for direction, delta in [("decrease (-20%)", -perturbation), ("increase (+20%)", perturbation)]:
            perturbed_weights = dict(weights)
            perturbed_weights[comp] = max(0.001, weights[comp] * (1.0 + delta))

            # Renormalize active weights
            norm_total = sum(perturbed_weights[k] for k in active_keys)
            perturbed_score = sum(
                scores[k] * (perturbed_weights[k] / norm_total)
                for k in active_keys
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
        "analysis_type": "composite_score_drift_analysis",
        "description": "Measures single-profile composite score drift under +/- weight perturbations. Not cohort ranking stability.",
        "base_score": round(base_score, 2),
        "subscores": scores,
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
    parser = argparse.ArgumentParser(description="Analyze health score composite-score drift under weight perturbations (volatility analysis)")
    parser.add_argument("--complexity", type=float, default=85.0, help="Complexity subscore (0-100)")
    parser.add_argument("--maintainability", type=float, default=95.0, help="Maintainability subscore (0-100)")
    parser.add_argument("--security", type=float, default=70.0, help="Security (Bandit) subscore (0-100)")
    parser.add_argument("--sast", type=float, default=80.0, help="SAST (Semgrep) subscore (0-100)")
    parser.add_argument("--secrets", type=float, default=90.0, help="Secrets (Gitleaks) subscore (0-100)")
    parser.add_argument("--vulnerabilities", type=float, default=75.0, help="Vulnerabilities (OSV) subscore (0-100)")
    parser.add_argument("--perturbation", type=float, default=0.20, help="Perturbation fraction (default: 0.20 for +/-20%)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    subscores = {
        "complexity": args.complexity,
        "maintainability": args.maintainability,
        "security": args.security,
        "sast": args.sast,
        "secrets": args.secrets,
        "vulnerabilities": args.vulnerabilities,
    }

    report = run_sensitivity_analysis(subscores, perturbation=args.perturbation)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=== Health Score Composite-Score Drift Analysis (Component Weight Volatility) ===")
        print("Note: This evaluates composite-score drift under +/- weight perturbations for a given repository subscore profile.")
        print("It does NOT measure cohort ranking stability across multiple repositories (which requires empirical cohort evaluation without fabricated data).")
        print(f"\nBase Composite Score: {report['base_score']}")
        print(f"Subscores: {subscores}")
        print(f"Perturbation: +/-{report['perturbation_percent']:.0f}%\n")
        print(f"{'Component':<18} {'Base Weight':<14} {'Max Drift':<12} {'Drift Ranking'}")
        print("-" * 65)
        for rank, item in enumerate(report["ranked_volatility"], 1):
            print(f"{item['component']:<18} {item['base_weight']:<14.2f} {item['max_drift']:<12.2f} #{rank}")
        print("\nConclusion: Components whose subscores deviate most from the baseline composite score exhibit the highest drift under weight perturbation.")


if __name__ == "__main__":
    main()

