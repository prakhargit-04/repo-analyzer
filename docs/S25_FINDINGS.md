# S25 Findings Report: Forensics & Verification

## Baseline Environment (A1)
- **OS**: Windows-11-10.0.26200-SP0 (win32)
- **Python**: 3.12.10 (AMD64)
- **Node**: v24.18.0
- **NPM**: 11.16.0
- **Git Commit**: `71a3793ce494d2d894172b3498f45c194e3638e5` (clean working tree)
- **Analyzers**:
  - `semgrep`: 1.177.0
  - `gitleaks`: 8.30.1
  - `bandit`: 1.9.4
  - `radon`: 6.0.1
  - `lizard`: 1.24.0
- **OSV Reachability**: `api.osv.dev` returned HTTP 200 (47,406 bytes)
- **Evidence Path**: `docs/s25_evidence/a1_forensics.txt`

---

## Health Score Breakdown & Explain Tool (A2)
Tool `scripts/explain_score.py` was constructed to call the production `compute_health_score(analysis)` function directly.

### Results on Evaluated Repositories:
1. **This Repository (`.`)**:
   - **Composite Score**: **52.11** (reproduced real number; not 64.8)
   - **Status**: `partial`
   - **Missing Components**: `['vulnerabilities']`
   - **Subscores**:
     - `complexity`: 91.08 (223 items, rank distribution: A:148, B:44, C:19, D:6, E:4, F:2)
     - `maintainability`: 66.94 (53 files, min MI=0.0, avg MI=66.9, max MI=100.0)
     - `security` (Bandit): 0.00 (HIGH=1, MEDIUM=3, LOW=33; penalty sum=102 >= 100)
     - `sast` (Semgrep): 0.00 (ERROR/HIGH=2, WARNING/MEDIUM=21, INFO/LOW=6; penalty sum=189 >= 100)
     - `secrets` (Gitleaks): 100.00 (0 secrets)
     - `vulnerabilities` (OSV): None (`unavailable`)
   - **Evidence Path**: `docs/s25_evidence/a2_explain_score_local.txt`

2. **`pytest-dev/iniconfig` (`v2.0.0`, commit `93f5930e668c0d1ddf4597e38dd0dea4e2665e7a`)**:
   - **Composite Score**: **84.44**
   - **Status**: `partial` (`vulnerabilities` unsupported)
   - **Subscores**: complexity: 85.00, maintainability: 57.48, security: 98.00, sast: 100.00, secrets: 100.00, vulnerabilities: None
   - **Evidence Path**: `docs/s25_evidence/a2_explain_score_iniconfig.txt`

3. **`pallets/itsdangerous` (`2.1.2`, commit `49d263f60b6f78df8924be51262eeb5216ab1468`)**:
   - **Composite Score**: **95.51**
   - **Status**: `partial` (`vulnerabilities` unsupported)
   - **Subscores**: complexity: 100.00, maintainability: 84.53, security: 98.00, sast: 100.00, secrets: 100.00, vulnerabilities: None
   - **Evidence Path**: `docs/s25_evidence/a2_explain_score_itsdangerous.txt`

---

## Analytical Findings (A3)

### 1. Scored vs Missing Components & Renormalization Drift
- Across all evaluated repositories, 5 of 6 components were scored (`complexity`, `maintainability`, `security`, `sast`, `secrets`).
- `vulnerabilities` is consistently missing (`unavailable` due to local OSV socket issues or `unsupported` when no lockfiles match).
- The base weights sum to `0.25 + 0.25 + 0.20 + 0.15 + 0.10 = 0.95`. Renormalization scales every scored weight by `1.0 / 0.95 = 1.05263` (+5.26%).
- This renormalization shifts the composite score upwards or downwards by up to 5% of the distance from 100 or 0 compared to a full 6-component run.

### 2. Double-Counting Between Bandit and Semgrep
- Bandit and Semgrep operate independently but scan overlapping rule domains (e.g. `eval`, shell injection, subprocess calls, insecure crypto).
- In the scoring formula: Bandit contributes `0.20` weight and Semgrep SAST contributes `0.15` weight (combined `0.35` of total health score).
- A single insecure construct (such as `subprocess.run(..., shell=True)`) triggers penalties in BOTH Bandit (HIGH: -15) and Semgrep (ERROR: -15), doubly docking 30 points across 35% of the composite score.

### 3. Scope Policy (`production_code_only`) Coverage
- `is_test_file()` in `pipeline/util.py` only filters paths matching `test/`, `tests/`, `testing/`, `conftest.py`, or `test_*` / `*_test.py`.
- It does **not** exclude:
  - `vendor/` or `third_party/` directories
  - Database migrations (`pipeline/db/migrations/versions/*.py`)
  - Standalone `fixtures/` directories outside `tests/`
  - Generated code directories
- Consequently, files in those directories are parsed and analyzed as production source code.

### 4. Scoring of Unknown Severities
- In `pipeline/health_score.py`:
  - **Bandit** (`_security_subscore`): `BANDIT_SEVERITY_PENALTY.get(str(sev).upper(), 2)` -> Defaults to **2** points (LOW penalty).
  - **Semgrep** (`_sast_subscore`): `SEMGREP_SEVERITY_PENALTY.get(sev, 5)` -> Defaults to **5** points (intermediate penalty between 2 and 7).

### 5. Findings Zero-Out Thresholds
- **Secrets** (Gitleaks): Penalty is `25.0 * len(findings)`. Exactly **4** secrets zero out the sub-score (`100 - 4*25 = 0.0`).
- **Vulnerabilities** (OSV): Penalty is `20.0 * len(findings)`. Exactly **5** vulnerabilities zero out the sub-score (`100 - 5*20 = 0.0`).

### 6. Non-Python Complexity Path
- When `complexity` (Radon CC) has status `unsupported`, `unavailable`, or `failed`, Radon subscore falls back to `_lizard_cc_to_points()` using Lizard complexity across 30+ languages (ranking cc <= 5 as 100, cc <= 10 as 85, ..., cc > 40 as 10).
- However, `maintainability` (Radon MI) has **no** fallback. Non-Python repositories always have `maintainability: None` (`unsupported`), forcing `reduced_component_set = True`.

---

## Cache Freshness & Fingerprint Sensitivity (A4)
- **Components in `analysis_config_fingerprint()`**:
  - `CACHE_SCHEMA_VERSION` (v6)
  - `ANALYZER_VERSION` (0.24.7)
  - `SOURCE_CHUNKER_VERSION` (1)
  - `EMBEDDING_PIPELINE_VERSION` (1)
  - `provider_name`, `model_name`, `provider_version`
  - `semgrep_ruleset_identity()`
- **Key Findings**:
  - **Commit SHA**: Included for fresh clones via `git_sha`; for local directories, `content-sha256` of all files is used.
  - **Embedding Provider**: Included in the key via `provider_name`, `model_name`, `provider_version`.
  - **Semgrep Ruleset**: Included; modifying a local rule file changes the fingerprint.
  - **Analyzer Availability**: **NOT** in `analysis_config_fingerprint()`. If an analyzer was missing/unavailable when a cache entry was created and subsequently installed, the cache key does not change, causing stale cache reuse.
- **Evidence Path**: `docs/s25_evidence/a4_cache_freshness.txt`

---

## Job Status Mapping (A5)

| State / Scenario | API Status | API Response Details | UI Component Display | Test Coverage |
| :--- | :--- | :--- | :--- | :--- |
| **`queued`** | `200` / `202` | `status: "queued"`, `progress: 0`, `run_id: null` | `ProgressStepper` in queued stage (0%), "Analysis in progress", no tabs | `tests/test_api.py`, `frontend/src/__tests__/dashboard.test.ts` |
| **`running`** | `200 OK` | `status: "<stage>"`, `progress: 10-90%`, `run_id: null` | Active stage spinner, progress bar animated, "Analysis in progress", no tabs | `tests/test_api.py`, `frontend/src/__tests__/dashboard.test.ts` |
| **`completed`** | `200 OK` | `status: "completed"`, `progress: 100%`, `run_id: "<id>"` | All stages green in `ProgressStepper`, full tabs (Overview, Findings, Files, Search, Assistant) | `tests/test_api.py`, `tests/test_regression.py`, `frontend/src/__tests__/dashboard.test.ts` |
| **`partial`** | `200 OK` | `status: "partial"`, `progress: 100%`, `run_id: "<id>"` | `ProgressStepper` in partial state, loads analysis with reduced component set banner | `tests/test_v0246_failure_states.py`, `frontend/src/__tests__/dashboard.test.ts` |
| **`failed`** | `200 OK` | `status: "failed"`, `error_message: "<msg>"`, `run_id: null` | `ProgressStepper` in failed state, error message banner displayed, no tabs | `tests/test_v0246_failure_states.py`, `frontend/src/__tests__/dashboard.test.ts` |
| **`stale-cleaned`** | `200 OK` | `status: "failed"`, `error_message: "Job marked failed on startup: stuck..."` | Red failed state in stepper with startup timeout error message | `tests/test_misc_guards.py`, `tests/test_v0246_failure_states.py` |
| **Unknown Job ID** | `404 Not Found` | `{"detail": "Job '<id>' not found"}` | Tries job fetch then analysis fetch; displays `API Error: Failed to fetch...` with "Back to Home" | `tests/test_api.py::test_get_job_not_found`, `frontend/src/__tests__/dashboard.test.ts` |
| **Unknown Analysis ID** | `404 Not Found` | `{"detail": "Analysis run '<id>' not found"}` | Displays `API Error: Analysis run '<id>' not found` card | `tests/test_api.py::test_get_analysis_not_found` |
| **Restart Mid-Job** | `500` / `200` | Process interrupted; on restart `cleanup_stale_jobs()` marks `failed` | Shows failed state with stuck timeout notice | `tests/test_regression.py::test_lifespan_stale_jobs_marked_failed` |

---

## Suspected Issues Confirmation Table (A6)

| ID | Finding | Evidence | Severity | Status | Fix Planned |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **S1** | `Dockerfile` hides migration errors (`2>/dev/null \|\| true`) and copies only `pipeline/`, omitting `alembic.ini` | `Dockerfile` line 28 has `COPY pipeline/ ./pipeline/`, line 43 has `python -m alembic upgrade head 2>/dev/null \|\| true` | **High** | **CONFIRMED** | Fix in Part C (copy `alembic.ini`, write entrypoint with `set -e`) |
| **S2** | `Dockerfile` uses Python 3.11-slim while CI uses Python 3.12 | `Dockerfile` line 2 & 15: `FROM python:3.11-slim`; `.github/workflows/ci.yml` line 25: `python-version: '3.12'` | **Medium** | **CONFIRMED** | Fix in Part C (update both stages to `python:3.12-slim`) |
| **S3** | `gitleaks` is not installed in the Docker image | `Dockerfile` installs only `gcc g++ git libpq-dev curl` and pip requirements; `gitleaks` binary absent | **Medium** | **CONFIRMED** | Fix in Part C (install pinned gitleaks with checksum verification) |
| **S4** | `docker-compose.yml` has no frontend service and uses obsolete `version: "3.9"` | `docker-compose.yml` defines only `db` and `backend` services; `version: "3.9"` on line 1 | **Medium** | **CONFIRMED** | Fix in Part C (add frontend service, remove version key, add healthchecks) |
| **S5** | CI workflow has no PostgreSQL test job or compose smoke test | `.github/workflows/ci.yml` contains `test`, `windows-cache-regression`, `frontend`, `analyzer-smoke`; zero postgres service jobs | **Medium** | **CONFIRMED** | Fix in Part C (add PostgreSQL service job, compose smoke job, mutation-checks) |
| **S6** | Health score output lacks validated marker and analyzer coverage metadata | `pipeline/health_score.py` `compute_health_score()` returns no `score_validation` or `analyzer_coverage` fields; frontend displays bare number | **High** | **CONFIRMED** | Fix in Part B (`score_validation`, `analyzer_coverage`, frontend honest banner) |
| **S7-npm** | Frontend dependencies contain 29 vulnerabilities (2 critical: `next`, `handlebars`; 7 high: `braces`, `sharp`, `source-map-js`) | `npm audit` in `frontend/` reported GHSA-vcvr-r3jv-pc5j (RCE in next/og), GHSA-xw65-4hp5-5hc7 (handlebars injection) | **Critical** | **CONFIRMED** | Fix in Part B (upgrade pinned vulnerable packages without breaking suites) |
| **S7-pip** | `pip-audit` missing from environment; direct packages verified | `pip-audit --version` not found; direct Python packages inspected | **Low** | **CONFIRMED** | Recorded as finding; audit step added in CI in Part C |

