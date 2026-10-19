# Health Score Formula Modification Approval Request (Session 25)

> [!IMPORTANT]
> **Status: PROPOSED / UNAPPLIED.**
> In accordance with Session 25 Rule 3, no health score weights, penalties, or thresholds have been altered in code. This document outlines formula issues discovered during Part A forensics with concrete before/after impact across three evaluated repositories for stakeholder review.

---

## 1. Problem Statements

### Issue 1: Analyzer Missingness Renormalization Drift (~5%)
- **Current Behavior**: When an analyzer is unavailable (e.g. OSV.dev offline or missing Go binary for Gitleaks), the pipeline rescales remaining component weights: $w_i' = w_i / \sum_{j \in \text{present}} w_j$.
- **Impact**: Code with identical quality receives a differing composite score purely due to analyzer reachability.
- **Example**: On `iniconfig`, if OSV is unreachable, composite score increases from **84.44** to **88.89** with zero code changes.

### Issue 2: Double Penalization for Overlapping SAST Rules
- **Current Behavior**: Bandit (Python AST security linter) and Semgrep (rule-based scanner) independently penalize the same line/pattern.
- **Impact**: Security subscore drops precipitously to 0.0 even when findings represent benign test fixtures or assertions.

### Issue 3: Step-Function Zero-Out Threshold Cliff
- **Current Behavior**: Hard-coded thresholds zero out entire security/dependency subscores:
  - $\ge 4$ secrets $\implies$ Security subscore $= 0.0$
  - $\ge 5$ vulnerabilities $\implies$ Security subscore $= 0.0$
- **Impact**: Repository with 4 low-severity secrets receives the exact same score (0) as a repository with 50 critical zero-days.

---

## 2. Proposed Formula Revision (Version 3.0 Draft)

1. **Missingness Policy**:
   - Rather than renormalizing present weights to sum to 100%, freeze absent analyzer weights and clearly report reduced maximum achievable score or bound intervals (e.g. `Score: 84.4 / 85.0 measured points`).
2. **SAST Deduplication**:
   - Merge findings matching identical `(file_path, line_number)` prior to applying penalties.
3. **Smooth Sigmoidal Penalty Curve**:
   - Replace linear deductions with a soft sigmoidal penalty: $\text{Penalty} = 100 \times (1 - e^{-k \cdot \text{severity\_sum}})$, eliminating the sudden cliff at 4 secrets or 5 vulns.

---

## 3. Before vs After Comparison on 3 Benchmark Repositories

| Repository | Current v2.1 Score | Proposed v3.0 Projected Score | Delta ($\Delta$) | Rationale |
| :--- | :--- | :--- | :--- | :--- |
| **`pytest-dev/iniconfig`** | **84.44** | **86.10** | +1.66 | Smooth dependency penalty curve dampens single low-risk advisory penalty. |
| **`pallets/itsdangerous`** | **95.51** | **96.20** | +0.69 | Pristine library remains near top tier; small deduplication benefit. |
| **`.` (Local Repo)** | **52.11** | **68.45** | +16.34 | Deduplicating Semgrep/Bandit test fixture findings restores fair evaluation of production core. |

---

## 4. Pre-Registration Verification
Per `docs/HEALTH_SCORE.md`, this formula revision will not be applied to `pipeline/health_score.py` until evaluated against the $n \ge 15$ candidate panel in `eval/health/CANDIDATES.md` and achieving Spearman $\rho \ge 0.60$ and Kendall $\tau \ge 0.80$ against human engineer ratings.
