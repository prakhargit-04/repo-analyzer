"""
Composite Health Score -- explicit formula, weights, normalization, AND
explicit failure handling. A failed tool must never look like a clean
repository: if a sub-score's source data has status "failed", that
sub-score is None and excluded from the composite (with weights
renormalized across whatever remains, not silently treated as zero
impact or perfect impact). The composite is then honestly labeled
"complete" or "partial" so nobody downstream mistakes a partial result
for a full one.

-------------------------------------------------------------------------
OVERALL STATUS -- "complete" requires EVERY component to be "success"
-------------------------------------------------------------------------
A component with status "partial" can still produce a usable sub-score
(computed from whatever results it did get) -- but that sub-score being
present is not the same claim as the analysis being complete. A previous
version of this function only looked at whether a sub-score was None (i.e.
whether the WEIGHT needed renormalizing), which meant a "partial" complexity
result that still returned a number caused the overall status to say
"complete" -- true for the arithmetic, false for what actually happened.
Overall status is now computed from the underlying component statuses
directly: "complete" iff complexity/maintainability/security are ALL
"success"; "failed" iff none of them produced a usable score; "partial"
otherwise (covers both "some missing" and "some present but not fully
successful").

-------------------------------------------------------------------------
SCOPE DECISION (previous version was inconsistent about this)
-------------------------------------------------------------------------
"Health" here means PRODUCTION CODE health, not the whole repository.
Test files are excluded from all three sub-scores by the same rule
(util.is_test_file), enforced upstream in static_analysis.py before any
of these functions see the data. This is a real design decision, not a
default: test code has different quality norms (e.g. `assert` is normal,
some duplication is normal, very high cyclomatic complexity in a
parametrized test is normal) and blending it into "how healthy is this
codebase" would penalize repos with good test coverage relative to repos
with none -- backwards incentive. Test file counts ARE still reported
(see static_analysis.py's `test_files_excluded`) so nothing is hidden.

-------------------------------------------------------------------------
SUB-SCORES (each normalized to 0-100, higher = healthier)
-------------------------------------------------------------------------
1. Complexity sub-score (weight 0.35)
   Source: radon cyclomatic-complexity rank per function (A best - F worst).
   Rank -> points:  A=100  B=85  C=70  D=50  E=30  F=10
   Sub-score = unweighted average of per-function points.

2. Maintainability sub-score (weight 0.35)
   Source: radon Maintainability Index (already 0-100 by construction).
   Sub-score = mean MI across files, clipped to [0, 100].

3. Security sub-score (weight 0.30)
   Source: bandit issue list (production files only).
   Start at 100, subtract per issue: HIGH -15, MEDIUM -7, LOW -2. Floor 0.

-------------------------------------------------------------------------
COMPOSITE AND FAILURE HANDLING
-------------------------------------------------------------------------
composite = sum(weight_i * subscore_i for available i) / sum(weight_i for available i)

If ALL sub-scores are unavailable, the composite is None with status
"failed" -- there is no such thing as a health score computed from zero
data, and this function will not pretend otherwise.

Resolution confidence from the call graph is reported alongside the
health score elsewhere in the pipeline output, never blended into it --
that measures analysis coverage, not code quality.

-------------------------------------------------------------------------
VALIDATION PLAN (to run in the evaluation phase, Month 4+)
-------------------------------------------------------------------------
- Assemble a small labeled set of repos with known quality reputations.
- Check the composite score ranks them as expected (Spearman correlation
  against a human-panel ranking).
- Run a weight-sensitivity sweep (+-10% per weight); if the labeled-set
  ranking flips, the weights are too brittle and need revisiting.
- Publish the labeled set, correlation number, and sweep result alongside
  the score itself so it is falsifiable, not just asserted.
"""
from __future__ import annotations

RANK_POINTS = {"A": 100, "B": 85, "C": 70, "D": 50, "E": 30, "F": 10}
SEVERITY_PENALTY = {"HIGH": 15, "MEDIUM": 7, "LOW": 2}
WEIGHTS = {"complexity": 0.35, "maintainability": 0.35, "security": 0.30}
VALID_COMPONENT_STATUSES = {"success", "partial", "failed"}


def _complexity_subscore(block: dict):
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] == "failed":
        return None
    results = block["results"]
    if not results:
        return 100.0  # genuinely no functions found -- success status confirms this, not a failure hiding as this
    points = [RANK_POINTS.get(r["rank"], 50) for r in results]
    return round(sum(points) / len(points), 2)


def _maintainability_subscore(block: dict):
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] == "failed":
        return None
    results = block["results"]
    if not results:
        return 100.0
    values = [max(0.0, min(100.0, r["maintainability_index"])) for r in results]
    return round(sum(values) / len(values), 2)


def _security_subscore(block: dict):
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] == "failed":
        return None
    score = 100.0
    for issue in block["results"]:
        score -= SEVERITY_PENALTY.get(issue["severity"].upper(), 2)
    return round(max(0.0, score), 2)


def _determine_overall_status(component_statuses: dict, available: dict) -> str:
    """
    "complete" requires every component to have actually succeeded -- not
    just "every component produced a non-None score". A "partial" component
    can still produce a usable number (computed from whatever results it
    did get before the failure), and a prior version of this function only
    checked whether scores were None, so a partial-but-numeric result was
    reported as an overall "complete" -- correct arithmetic, false claim.

    "failed" iff nothing usable came back from any component at all.
    "partial" covers both "some component fully missing" and "some
    component present but not fully successful" -- both mean the caller
    should not treat this result as a full, trustworthy analysis.
    """
    if not available:
        return "failed"
    if set(component_statuses.values()) == {"success"}:
        return "complete"
    return "partial"


def compute_health_score(analysis: dict) -> dict:
    component_statuses = {
        "complexity": analysis["complexity"]["status"],
        "maintainability": analysis["maintainability"]["status"],
        "security": analysis["security"]["status"],
    }

    comp = _complexity_subscore(analysis["complexity"])
    maint = _maintainability_subscore(analysis["maintainability"])
    sec = _security_subscore(analysis["security"])

    subs = {"complexity": comp, "maintainability": maint, "security": sec}
    available = {k: v for k, v in subs.items() if v is not None}
    missing = [k for k, v in subs.items() if v is None]

    overall_status = _determine_overall_status(component_statuses, available)

    if not available:
        return {
            "composite_health_score": None,
            "status": overall_status,
            "sub_scores": subs,
            "component_statuses": component_statuses,
            "missing_components": missing,
            "reason": "All underlying analysis tools failed; no health score can be computed from zero data.",
        }

    weight_sum = sum(WEIGHTS[k] for k in available)
    composite = round(sum(WEIGHTS[k] * v for k, v in available.items()) / weight_sum, 2)

    return {
        "composite_health_score": composite,
        "status": overall_status,
        "sub_scores": subs,
        "component_statuses": component_statuses,
        "missing_components": missing,
        "weights_used": {k: round(WEIGHTS[k] / weight_sum, 4) for k in available},
        "weights_renormalized": missing != [],
        "formula": "weighted average of available sub-scores; weights renormalized "
                   "to sum to 1 if any component is missing (never treated as 0 or 100)",
        "scope_policy": analysis.get("scope_policy", "production_code_only"),
        "note": "Call-graph resolution confidence is reported separately "
                "(graph_builder.graph_summary) and intentionally NOT blended "
                "into this score -- it measures analysis coverage, not code quality. "
                "'status' reflects whether EVERY component fully succeeded, not "
                "merely whether a numeric score could be computed -- a 'partial' "
                "component can still contribute a number without the overall "
                "result being 'complete'.",
    }
