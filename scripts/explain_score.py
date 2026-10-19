#!/usr/bin/env python3
"""
Explain Health Score breakdown for a repository or analysis JSON.
Calls the real compute_health_score without reimplementing it.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from typing import Dict, Any, Optional

# Ensure pipeline is importable
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPELINE_DIR = os.path.join(REPO_ROOT, "pipeline")
if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from health_score import (
    compute_health_score,
    DEFAULT_WEIGHTS_V2,
    LEGACY_WEIGHTS,
    BANDIT_SEVERITY_PENALTY,
    SEMGREP_SEVERITY_PENALTY,
    RANK_POINTS,
)


def get_finding_counts_and_arithmetic(comp_name: str, comp_block: dict, lizard_block: Optional[dict] = None) -> tuple[str, str]:
    """Returns (finding counts summary, penalty arithmetic string)."""
    status = comp_block.get("status", "unavailable")
    results = comp_block.get("results", [])

    if comp_name == "complexity":
        if status in ("failed", "unsupported", "unavailable"):
            if lizard_block and lizard_block.get("status") in ("success", "partial"):
                liz_results = lizard_block.get("results", [])
                if not liz_results:
                    return "0 functions (Lizard fallback)", "100.0 (no functions)"
                ccs = [r.get("cyclomatic_complexity", 1) for r in liz_results]
                return f"{len(liz_results)} functions (Lizard fallback, avg CC={sum(ccs)/len(ccs):.1f})", f"sum(lizard_points)/{len(liz_results)}"
            return "0 functions (no data)", "N/A (unsupported/unavailable)"
        if not results:
            return "0 functions", "100.0 (no functions)"
        rank_counts = {}
        for r in results:
            rnk = r.get("rank", "C")
            rank_counts[rnk] = rank_counts.get(rnk, 0) + 1
        rank_str = ", ".join(f"{k}:{v}" for k, v in sorted(rank_counts.items()))
        return f"{len(results)} items ({rank_str})", f"sum(rank_points)/{len(results)}"

    elif comp_name == "maintainability":
        if status in ("failed", "unsupported", "unavailable"):
            return "0 files", "N/A (unsupported/unavailable)"
        if not results:
            return "0 files", "100.0 (no files)"
        mis = [float(r.get("maintainability_index", 100.0)) for r in results]
        return f"{len(results)} files (min MI={min(mis):.1f}, avg MI={sum(mis)/len(mis):.1f}, max MI={max(mis):.1f})", f"sum(MI)/{len(results)}"

    elif comp_name == "security":
        if status in ("failed", "unsupported", "unavailable"):
            return "0 issues", "N/A (unsupported/unavailable)"
        counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for r in results:
            sev = str(r.get("severity", "")).upper()
            counts[sev] = counts.get(sev, 0) + 1
        cnt_str = f"HIGH={counts.get('HIGH',0)}, MEDIUM={counts.get('MEDIUM',0)}, LOW={counts.get('LOW',0)}"
        arithmetic = f"max(0.0, 100 - ({counts.get('HIGH',0)}*15 + {counts.get('MEDIUM',0)}*7 + {counts.get('LOW',0)}*2))"
        return cnt_str, arithmetic

    elif comp_name == "sast":
        if status in ("failed", "unsupported", "unavailable"):
            return "0 findings", "N/A (unsupported/unavailable)"
        counts = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        for r in results:
            sev = str(r.get("severity", "INFO")).upper()
            if sev in ("ERROR", "HIGH"):
                counts["ERROR"] += 1
            elif sev in ("WARNING", "MEDIUM"):
                counts["WARNING"] += 1
            else:
                counts["INFO"] += 1
        cnt_str = f"ERROR/HIGH={counts['ERROR']}, WARNING/MEDIUM={counts['WARNING']}, INFO/LOW={counts['INFO']}"
        arithmetic = f"max(0.0, 100 - ({counts['ERROR']}*15 + {counts['WARNING']}*7 + {counts['INFO']}*2))"
        return cnt_str, arithmetic

    elif comp_name == "secrets":
        if status in ("failed", "unsupported", "unavailable"):
            return "0 findings", "N/A (unsupported/unavailable)"
        cnt = len(results)
        return f"{cnt} secrets detected", f"max(0.0, 100.0 - (25.0 * {cnt}))"

    elif comp_name == "vulnerabilities":
        if status in ("failed", "unsupported", "unavailable"):
            return "0 findings", "N/A (unsupported/unavailable)"
        cnt = len(results)
        return f"{cnt} vulnerabilities detected", f"max(0.0, 100.0 - (20.0 * {cnt}))"

    return f"{len(results)} items", "N/A"


def explain(analysis: dict, title: str = "Repository Health Score Breakdown") -> str:
    score_res = compute_health_score(analysis)
    has_v2 = any(k in analysis for k in ("semgrep_findings", "gitleaks_findings", "osv_vulnerabilities"))
    base_weights = DEFAULT_WEIGHTS_V2 if has_v2 else LEGACY_WEIGHTS

    component_keys = ["complexity", "maintainability", "security"]
    if has_v2:
        component_keys.extend(["sast", "secrets", "vulnerabilities"])

    mapping = {
        "complexity": analysis.get("complexity", {"status": "unavailable"}),
        "maintainability": analysis.get("maintainability", {"status": "unavailable"}),
        "security": analysis.get("security", {"status": "unavailable"}),
        "sast": analysis.get("semgrep_findings", {"status": "unavailable"}),
        "secrets": analysis.get("gitleaks_findings", {"status": "unavailable"}),
        "vulnerabilities": analysis.get("osv_vulnerabilities", {"status": "unavailable"}),
    }

    sub_scores = score_res.get("sub_scores", {})
    weights_used = score_res.get("weights_used", {})
    comp_statuses = score_res.get("component_statuses", {})
    lizard_block = analysis.get("lizard_complexity")

    lines = []
    lines.append(f"============================================================")
    lines.append(f" {title}")
    lines.append(f"============================================================")
    lines.append(f"Composite Score        : {score_res.get('composite_health_score')}")
    lines.append(f"Status                 : {score_res.get('status')}")
    lines.append(f"Formula Version        : {score_res.get('formula_version')}")
    lines.append(f"Reduced Component Set  : {score_res.get('reduced_component_set')}")
    lines.append(f"Missing Components     : {score_res.get('missing_components')}")
    lines.append(f"Weights Renormalized   : {score_res.get('weights_renormalized')}")
    lines.append(f"------------------------------------------------------------")
    lines.append(f"{'Component':<16} | {'Status':<11} | {'Subscore':<8} | {'Base Wt':<7} | {'Norm Wt':<7} | {'Contrib':<7}")
    lines.append(f"-----------------+-------------+----------+---------+---------+--------")

    total_contrib = 0.0
    for comp in component_keys:
        status = comp_statuses.get(comp, "unavailable")
        sub = sub_scores.get(comp)
        base_w = base_weights.get(comp, 0.0)
        norm_w = weights_used.get(comp, 0.0)
        sub_str = f"{sub:.2f}" if sub is not None else "None"
        contrib = (norm_w * sub) if sub is not None else 0.0
        total_contrib += contrib
        lines.append(f"{comp:<16} | {status:<11} | {sub_str:<8} | {base_w:<7.2f} | {norm_w:<7.4f} | {contrib:<7.2f}")

    lines.append(f"------------------------------------------------------------")
    lines.append(f"Sum of Weighted Contributions: {total_contrib:.2f}")
    lines.append(f"\nComponent Details & Penalty Arithmetic:")
    for comp in component_keys:
        block = mapping[comp]
        status = comp_statuses.get(comp, "unavailable")
        counts_str, arith_str = get_finding_counts_and_arithmetic(comp, block, lizard_block)
        sub = sub_scores.get(comp)
        sub_str = f"{sub:.2f}" if sub is not None else "None"
        lines.append(f"  * {comp.upper()}:")
        lines.append(f"      Status             : {status}")
        lines.append(f"      Findings / Counts  : {counts_str}")
        lines.append(f"      Penalty Arithmetic : {arith_str}")
        lines.append(f"      Sub-score          : {sub_str}")

    if score_res.get("note"):
        lines.append(f"\nScore Note:")
        lines.append(f"  {score_res.get('note')}")

    lines.append(f"============================================================\n")
    return "\n".join(lines)


def analyze_target(target: str) -> dict:
    if os.path.isfile(target) and target.endswith(".json"):
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
            # could be top-level pipeline output or static_analysis output
            if "complexity" in data or "semgrep_findings" in data:
                return data
            raise ValueError(f"JSON file {target} does not contain static analysis keys")

    from parser_interface import parse_repository
    import static_analysis
    import clone

    repo_dir = target
    cleanup = False
    if target.startswith("http://") or target.startswith("https://") or target.startswith("git@"):
        import tempfile
        temp_dir = tempfile.mkdtemp(prefix="explain_repo_")
        clone.clone_repository(target, temp_dir)
        repo_dir = temp_dir
        cleanup = True

    try:
        parse_results = parse_repository(repo_dir)
        parse_results.sort(key=lambda r: r.file)
        parsed_files_rel = [r.file for r in parse_results if not r.parse_error]
        analysis = static_analysis.analyze_repository(repo_dir, parsed_files_rel)
        return analysis
    finally:
        if cleanup:
            import shutil
            shutil.rmtree(repo_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Explain Health Score breakdown.")
    parser.add_argument("target", nargs="?", default=".", help="Repository path, URL, or analysis JSON file (default: .)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    args = parser.parse_args()

    analysis = analyze_target(args.target)
    if args.json:
        score = compute_health_score(analysis)
        print(json.dumps(score, indent=2))
    else:
        text = explain(analysis, title=f"Health Score for: {args.target}")
        print(text)


if __name__ == "__main__":
    main()
