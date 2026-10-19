# Repository Health Score Specification & Governance

## Formula Version: 2.1 (Heuristic / Not Empirically Validated)

> [!WARNING]
> **Validation Status: UNVALIDATED.**
> The weights, penalties, and thresholds defined in `pipeline/health_score.py` are heuristic expert choices. They have **not** undergone empirical validation against blind human developer assessments or post-release defect data.

---

## Weight Catalog & Sourcing

| Component | Default Weight (v2) | Sourcing / Rationale | Sourcing Status |
| :--- | :--- | :--- | :--- |
| **Maintainability** | `0.35` | Based on Radon Maintainability Index (Coleman et al. / SEI formula). Measures code structural comprehensibility. | **HEURISTIC** (weight choice is arbitrary heuristic; MI formula itself is sourced) |
| **Complexity** | `0.30` | Based on McCabe Cyclomatic Complexity (McCabe 1976) via Radon/Lizard rank bins. | **HEURISTIC** (weight choice is arbitrary heuristic; rank bins are sourced) |
| **Security** | `0.20` | Aggregated findings from Semgrep, Bandit, and Gitleaks. | **HEURISTIC** (weight and penalty curves are heuristics) |
| **Dependencies** | `0.15` | Known dependency vulnerabilities from OSV.dev. | **HEURISTIC** (weight and penalty curves are heuristics) |

---

## Constant & Penalty Catalog

| Constant / Parameter | Value | Domain / Usage | Sourcing Status |
| :--- | :--- | :--- | :--- |
| `RADON_MI_RANK` | A: 100, B: 80, C: 60 | Maintainability rank mapping to 0-100 scale | **SOURCED** (Radon documentation) |
| `LIZARD_CC_RANK` | A (1-5): 100, B (6-10): 80, C (11-20): 60, D (21-30): 40, E (31-40): 20, F (>40): 0 | Complexity score bins | **SOURCED** (NIST / Software Engineering Institute complexity risk bands) |
| `BANDIT_HIGH` | -20 pts | Security deduction per High severity finding | **HEURISTIC** |
| `BANDIT_MEDIUM` | -10 pts | Security deduction per Medium severity finding | **HEURISTIC** |
| `BANDIT_LOW` | -3 pts | Security deduction per Low severity finding | **HEURISTIC** |
| `SEMGREP_ERROR` | -20 pts | Security deduction per Error level finding | **HEURISTIC** |
| `SEMGREP_WARNING` | -10 pts | Security deduction per Warning level finding | **HEURISTIC** |
| `SEMGREP_INFO` | -3 pts | Security deduction per Info level finding | **HEURISTIC** |
| `OSV_CRITICAL` | -25 pts | Dependency deduction per Critical CVE | **HEURISTIC** |
| `OSV_HIGH` | -20 pts | Dependency deduction per High CVE | **HEURISTIC** |
| `OSV_MEDIUM` | -10 pts | Dependency deduction per Medium CVE | **HEURISTIC** |
| `OSV_LOW` | -3 pts | Dependency deduction per Low CVE | **HEURISTIC** |
| `SECRET_ZERO_THRESHOLD` | 4 secrets | Triggers 0.0 security subscore | **HEURISTIC** |
| `VULN_ZERO_THRESHOLD` | 5 vulns | Triggers 0.0 security subscore | **HEURISTIC** |
| `WEIGHT_RENORMALIZATION` | $w_i' = \frac{w_i}{\sum_{j \in \text{present}} w_j}$ | Dynamic scaling when analyzers are unavailable | **HEURISTIC** (causes up to ~5% composite score drift on identical code) |

---

## Pre-Registered Empirical Validation Plan

To validate or refine these weights without bias, any future revision to the health score formula must satisfy the following pre-registered empirical criteria:

1. **Sample Size & Diversity**:
   - $n \ge 15$ public repositories across at least 3 distinct domains (e.g., CLI utilities, web frameworks, systems libraries).
2. **Correlation Threshold**:
   - **Spearman Rank Correlation** ($\rho$): $\ge 0.60$ with blind human senior engineer ratings ($p < 0.05$).
3. **Pairwise Ranking Accuracy**:
   - **Kendall's Tau** ($\tau$): $\ge 0.80$ on clearly distinct repository pairs (e.g., production libraries vs intentionally vulnerable benchmark repositories).
4. **No Ad-Hoc Tuning**:
   - Weight proposals cannot be retrofitted against evaluation candidates after evaluating them.
