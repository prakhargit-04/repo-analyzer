"""
Composite Health Score v2 -- explicit formula, weights, normalization, AND
explicit failure handling across all analyzers.

Scoring components (Health Score v2):
1. complexity (Radon Cyclomatic Complexity)     - Weight: 0.25
2. maintainability (Radon Maintainability Index)- Weight: 0.25
3. security (Bandit Security Scanner)          - Weight: 0.20
4. sast (Semgrep Static Security Analysis)      - Weight: 0.15
5. secrets (Gitleaks Secret Detection)          - Weight: 0.10
6. vulnerabilities (OSV Dependency Scanner)     - Weight: 0.05

Informational-only analyzers:
- lizard_complexity: Language-agnostic cyclomatic complexity across 30+ languages.
  Informational only to avoid double-counting complexity with Radon CC.

Backward compatibility:
- If input analysis contains ONLY legacy 3 components ("complexity",
  "maintainability", "security"), default weights of 0.35, 0.35, 0.30 are used,
  producing identical composite scores to Health Score v1.

Status semantics:
- "complete": every expected scoring component produced status "success".
- "failed": no scoring component produced a usable numeric subscore.
- "partial": at least one scoring component produced a numeric subscore, but at least
  one scoring component was partial, failed, unsupported, or unavailable.
"""
from __future__ import annotations
from typing import Dict, Any, Optional

RANK_POINTS = {"A": 100, "B": 85, "C": 70, "D": 50, "E": 30, "F": 10}
BANDIT_SEVERITY_PENALTY = {"HIGH": 15, "MEDIUM": 7, "LOW": 2}
SEMGREP_SEVERITY_PENALTY = {"HIGH": 15, "ERROR": 15, "WARNING": 15, "MEDIUM": 5, "INFO": 5}

# Health Score v2 6-component weights
DEFAULT_WEIGHTS_V2 = {
    "complexity": 0.25,
    "maintainability": 0.25,
    "security": 0.20,
    "sast": 0.15,
    "secrets": 0.10,
    "vulnerabilities": 0.05,
}

# Legacy Health Score v1 3-component weights
LEGACY_WEIGHTS = {
    "complexity": 0.35,
    "maintainability": 0.35,
    "security": 0.30,
}

VALID_COMPONENT_STATUSES = {"success", "partial", "failed", "unsupported", "unavailable"}


def _complexity_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    results = block.get("results", [])
    if not results:
        return 100.0
    points = [RANK_POINTS.get(r.get("rank", "C"), 50) for r in results]
    return round(sum(points) / len(points), 2)


def _maintainability_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    results = block.get("results", [])
    if not results:
        return 100.0
    values = [max(0.0, min(100.0, float(r.get("maintainability_index", 100.0)))) for r in results]
    return round(sum(values) / len(values), 2)


def _security_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    score = 100.0
    for issue in block.get("results", []):
        score -= BANDIT_SEVERITY_PENALTY.get(str(issue.get("severity", "")).upper(), 2)
    return round(max(0.0, score), 2)


def _sast_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    score = 100.0
    for finding in block.get("results", []):
        sev = str(finding.get("severity", "INFO")).upper()
        score -= SEMGREP_SEVERITY_PENALTY.get(sev, 5)
    return round(max(0.0, score), 2)


def _secrets_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    findings = block.get("results", [])
    score = 100.0 - (25.0 * len(findings))
    return round(max(0.0, score), 2)


def _vulnerabilities_subscore(block: dict) -> Optional[float]:
    if block["status"] not in VALID_COMPONENT_STATUSES:
        raise ValueError(f"Unknown analysis status: {block['status']!r}")
    if block["status"] in ("failed", "unsupported", "unavailable"):
        return None
    findings = block.get("results", [])
    score = 100.0 - (20.0 * len(findings))
    return round(max(0.0, score), 2)


def _determine_overall_status(component_statuses: dict, available: dict) -> str:
    if not available:
        return "failed"
    if set(component_statuses.values()) == {"success"}:
        return "complete"
    return "partial"


def compute_health_score(analysis: dict) -> dict:
    # Determine whether analysis contains new v2 analyzers or is legacy v1
    has_v2_keys = any(
        k in analysis
        for k in ("semgrep_findings", "gitleaks_findings", "osv_vulnerabilities")
    )

    if has_v2_keys:
        expected_components = {
            "complexity": analysis.get("complexity", {"status": "unavailable"}),
            "maintainability": analysis.get("maintainability", {"status": "unavailable"}),
            "security": analysis.get("security", {"status": "unavailable"}),
            "sast": analysis.get("semgrep_findings", {"status": "unavailable"}),
            "secrets": analysis.get("gitleaks_findings", {"status": "unavailable"}),
            "vulnerabilities": analysis.get("osv_vulnerabilities", {"status": "unavailable"}),
        }
        weights_config = DEFAULT_WEIGHTS_V2
    else:
        expected_components = {
            "complexity": analysis.get("complexity", {"status": "unavailable"}),
            "maintainability": analysis.get("maintainability", {"status": "unavailable"}),
            "security": analysis.get("security", {"status": "unavailable"}),
        }
        weights_config = LEGACY_WEIGHTS

    component_statuses = {k: comp.get("status", "unavailable") for k, comp in expected_components.items()}

    subs: Dict[str, Optional[float]] = {
        "complexity": _complexity_subscore(expected_components["complexity"]),
        "maintainability": _maintainability_subscore(expected_components["maintainability"]),
        "security": _security_subscore(expected_components["security"]),
    }
    if has_v2_keys:
        subs["sast"] = _sast_subscore(expected_components["sast"])
        subs["secrets"] = _secrets_subscore(expected_components["secrets"])
        subs["vulnerabilities"] = _vulnerabilities_subscore(expected_components["vulnerabilities"])

    available = {k: v for k, v in subs.items() if v is not None}
    missing = [k for k, v in subs.items() if v is None]

    overall_status = _determine_overall_status(component_statuses, available)

    informational_analyzers = ["lizard_complexity"] if "lizard_complexity" in analysis else []

    if not available:
        return {
            "composite_health_score": None,
            "status": overall_status,
            "sub_scores": subs,
            "component_statuses": component_statuses,
            "missing_components": missing,
            "weights_used": {},
            "weights_renormalized": True,
            "formula": "Weighted average of available sub-scores; weights renormalized to sum to 1.0 if any component is missing (never treated as 0 or 100).",
            "informational_analyzers": informational_analyzers,
            "reason": "All underlying scoring analysis tools failed or were unavailable; no health score can be computed from zero data.",
            "scope_policy": analysis.get("scope_policy", "production_code_only"),
            "note": "Informational analyzers (such as lizard_complexity) are captured separately and do not contribute to scoring calculation.",
        }

    weight_sum = sum(weights_config[k] for k in available)
    composite = round(sum(weights_config[k] * v for k, v in available.items()) / weight_sum, 2)
    weights_used = {k: round(weights_config[k] / weight_sum, 4) for k in available}

    return {
        "composite_health_score": composite,
        "status": overall_status,
        "sub_scores": subs,
        "component_statuses": component_statuses,
        "missing_components": missing,
        "weights_used": weights_used,
        "weights_renormalized": len(missing) > 0 or len(available) < len(weights_config),
        "formula": "Weighted average of available sub-scores (complexity: 0.25, maintainability: 0.25, security: 0.20, sast: 0.15, secrets: 0.10, vulnerabilities: 0.05); weights renormalized to sum to 1.0 if any component is unavailable/failed/unsupported (never treated as 0 or 100).",
        "informational_analyzers": informational_analyzers,
        "scope_policy": analysis.get("scope_policy", "production_code_only"),
        "note": "Call-graph resolution confidence is reported separately (graph_builder.graph_summary) and intentionally NOT blended into this score. Lizard complexity is informational only and excluded from scoring to prevent double-counting with Radon CC. 'status' reflects whether EVERY scoring component fully succeeded.",
    }

