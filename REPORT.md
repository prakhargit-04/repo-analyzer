# Session 25 Production-Trust Verification Report
**Baseline:** Repo Analyzer v0.24.7 $\to$ **Current:** Repo Analyzer v0.25.0  
**Date:** October 19, 2026  
**Status:** All Production-Trust Deliverables Completed (Parts A to G)

---

## 1. Executive Summary & Baseline vs v0.25.0 Changes

Session 25 executed a full production-trust pass across the Repo Analyzer stack. The primary architectural objective was replacing heuristic and unverified claims with transparent provenance, adding honest badges across the frontend and API, securing containerization and CI pipelines, and establishing rigorous, blind evaluation harnesses.

### Key Changes Summary
1. **Health Score Honesty**:
   - Added `score_validation` (`{validated: false, basis: "heuristic weights not empirically validated", formula_version: "2.1"}`) and `analyzer_coverage` to API and DB storage layers.
   - Added prominent UI badge `"Calculated score - not validated"` and a clear notice banner when subscores use `reduced_component_set`.
2. **Dependency & CVE Hardening**:
   - Upgraded Next.js and eslint-config-next to `16.4.2` to eliminate critical GHSA advisories.
3. **Frontend Resilience**:
   - Resolved 404 infinite loading screens with a clear "Analysis Not Found" state card.
   - Added explicit banners for failed or stale-cleaned jobs.
4. **DevOps & Production Governance**:
   - Created `docs/GOVERNANCE.md` (SLA, rate limits, incident runbooks, security disclosures).
   - Created hardened `docker/entrypoint.sh` with strict database connectivity checks and zero-tolerance migration failure.
   - Pinned `gitleaks 8.21.2` with sha256 checksum in Dockerfile, non-root user `appuser`, and automated healthcheck.
   - Created multi-stage `frontend/Dockerfile` (`node:22-alpine`) and integrated it into `docker-compose.yml`.
   - Hardened `.github/workflows/ci.yml` with a real PostgreSQL 16 service integration test job, Docker compose smoke test job, mutation checks, and pinned GitHub Actions.
5. **Independent Evaluation Harnesses**:
   - **Graph Accuracy**: 5 candidate repos across Python, Java, JS/TS; stratified edge sampling (`eval/graph/generate_sheet.py`); independent Python AST import cross-check oracle (`eval/graph/import_oracle.py`); metrics calculator with Wilson score 95% confidence intervals (`eval/graph/metrics.py`). Honest unreviewed status preserved (`0 of N labels reviewed`).
   - **RAG & Retrieval Accuracy**: Extended dataset to 30 questions (20 answerable with exact line numbers, 10 negative probes testing hallucination resistance); added BM25 lexical retriever baseline comparing against vector search; built budget-capped RAG evaluation script (`eval/rag/eval_rag.py`).
   - **Health Score Validation**: Cataloged all weights/penalties in `docs/HEALTH_SCORE.md`; pre-registered empirical validation thresholds (Spearman $\rho \ge 0.60$, Kendall $\tau \ge 0.80$); proposed 15 candidate repositories in `eval/health/CANDIDATES.md`; built sensitivity analysis (`eval/health/sensitivity.py`) and blind rating sheet generator/correlation script (`eval/health/correlation.py`).

---

## 2. Part-by-Part Status Table

| Part | Description | Status | Evidence Path | Key Verification Findings |
| :--- | :--- | :--- | :--- | :--- |
| **Part A** | Forensic Analysis & Baseline Audit | **DONE** | `docs/s25_evidence/a1_forensics.txt`<br>`docs/s25_evidence/a2_explain_score_*.txt`<br>`docs/s25_evidence/a4_cache_freshness.txt`<br>`docs/s25_evidence/a7_npm_audit.txt`<br>`docs/S25_FINDINGS.md` | Audited versions (Python 3.12.10, Node 24.18.0, Semgrep 1.177.0, Bandit 1.9.4, Gitleaks 8.30.1). Evaluated scores: local repo (52.11), iniconfig (84.44), itsdangerous (95.51). Confirmed S1-S7. |
| **Part B** | Fix Confirmed & Honesty Bumping | **DONE** | `tests/test_s25_production_trust.py`<br>`frontend/src/__tests__/components.test.tsx`<br>`frontend/src/__tests__/dashboard.test.ts` | B1-B4 completed. Honesty metadata persisted and rendered. Next.js updated to 16.4.2. Version bumped to v0.25.0. |
| **Part C** | Governance, Docker, CI Hardening | **DONE** | `docs/GOVERNANCE.md`<br>`docker/entrypoint.sh`<br>`Dockerfile`<br>`frontend/Dockerfile`<br>`docker-compose.yml`<br>`.github/workflows/ci.yml` | Full governance manual, entrypoint DB wait loop, multi-stage compose, postgres CI test job, compose smoke job, pinned action versions. |
| **Part D** | Graph Accuracy Harness | **DONE** | `eval/graph/CANDIDATES.md`<br>`eval/graph/schema.json`<br>`eval/graph/template.csv`<br>`eval/graph/generate_sheet.py`<br>`eval/graph/import_oracle.py`<br>`eval/graph/metrics.py`<br>`eval/graph/samples/iniconfig_sample.csv`<br>`tests/test_graph_eval_metrics.py` | 5 benchmark repos proposed. Stratified sampling across `calls`, `imports`, `inherits`, `contains`. 100% agreement on iniconfig AST import oracle. Wilson score 95% CI unit tests passed. Recall strictly outputs `None` (unmeasured) without negative markers (preventing false 100% recall). Status strictly enforces full review quorum (`NOT VALIDATED` / `INCOMPLETE` / `VALIDATED`). |
| **Part E** | Real AI / RAG Harness | **DONE** | `eval/questions.json`<br>`eval/rag/retrieval_comparison.py`<br>`eval/rag/eval_rag.py`<br>`eval/results/S25E_REPORT.md` | 30 questions cataloged (20 answerable with line evidence, 10 negative probes). Vector vs BM25 baseline evaluated on iniconfig (Recall@5 = 100%, BM25 MRR = 0.7333). RAG evaluator false-success behavior eliminated: dry-run mock outputs `NOT RUN (DRY RUN / MOCK ONLY)` with `None` for citation precision/recall rather than fabricating 100% success. |
| **Part F** | Score Validation Harness | **DONE** | `docs/HEALTH_SCORE.md`<br>`eval/health/CANDIDATES.md`<br>`eval/health/sensitivity.py`<br>`eval/health/rating_sheet.py`<br>`eval/health/rating_sheet.csv`<br>`eval/health/correlation.py`<br>`tests/test_health_eval_correlation.py` | Complete weights/constants catalog with SOURCED vs HEURISTIC annotations. Pre-registered validation thresholds ($n \ge 15$, $\rho \ge 0.60$, $\tau \ge 0.80$). Sensitivity analysis updated to cover all 6 canonical Health Score v2 components (`complexity`, `maintainability`, `security`, `sast`, `secrets`, `vulnerabilities`). Correlation script enforces $n \ge 15$ quorum before claiming `VALIDATED`. |
| **Part G** | The One Verification | **DONE** | `docs/s25_evidence/g1_backend_test.txt`<br>`docs/s25_evidence/g2_mutation_checks.txt`<br>`docs/s25_evidence/g3_hygiene.txt`<br>`docs/s25_evidence/g4_pyflakes.txt`<br>`docs/s25_evidence/g5_docker_smoke.txt` | **Backend Suite**: 917 passed, 12 skipped, 0 failed in 334.56s.<br>**Frontend Suite**: 85 passed, 0 failed.<br>**Frontend Build**: Typecheck clean, ESLint clean, Next.js build clean.<br>**Mutation Checks**: All 4 mutations killed.<br>**Repo Hygiene**: Zero forbidden artifacts.<br>**Pyflakes**: Zero errors.<br>**Docker Smoke & CI**: Multi-stage docker-compose, PostgreSQL 16 migrations, and npm audit passing. |

---

## 3. Outstanding Human Inputs Needed

To transition the evaluation harnesses from `HARNESS BUILT` to `EMPIRICALLY VALIDATED`, the following human expert inputs are required:

1. **Graph Accuracy Labels (`eval/graph/`)**:
   - Open `eval/graph/samples/iniconfig_sample.csv` (and sheets for other candidate repos generated via `eval/graph/generate_sheet.py`).
   - A qualified software engineer must inspect each source and target code location and fill the `label` column with `TP`, `FP`, or `AMBIGUOUS`.
   - Run `python eval/graph/metrics.py eval/graph/samples/iniconfig_sample.csv` to calculate the final validated precision, recall, and Wilson 95% confidence intervals.
2. **Health Score Blind Ratings (`eval/health/`)**:
   - Senior engineers must review the 15 candidate repositories in `eval/health/rating_sheet.csv` without looking at algorithmic scores.
   - Populate `human_rating_1_to_5` (1 = critical technical debt, 5 = exemplary clean architecture) and `notes`.
   - Run `python eval/health/correlation.py eval/health/rating_sheet.csv` to compute real Spearman rank correlation and Kendall tau against the pipeline's composite score.
3. **Live AI / RAG Validation (`eval/rag/`)**:
   - Provide an `OPENAI_API_KEY` or `GEMINI_API_KEY` in the environment.
   - Run `python eval/rag/eval_rag.py` to execute real queries within the pre-registered budget ($1.00 / 30 queries cap) to measure citation precision and negative probe hallucination rates.

---

## 4. Formula Approval Requests

Formula issues identified during Part A forensics are pre-registered in `docs/S25_FORMULA_APPROVAL_REQUEST.md`:
- **Analyzer Missingness Drift**: Rescaling weights when an analyzer is unavailable shifts scores up to ~5% on identical code.
- **Double Counting**: Bandit and Semgrep both penalize the same security patterns.
- **Zero-Out Cliffs**: Hardcoded step functions at 4 secrets or 5 vulnerabilities zero out entire subscores.
- **Action**: Per Session 25 Rule 3, no weights, penalties, or thresholds were modified in code. A formula revision to v3.0 is proposed and awaiting empirical rating correlation data.

---

## 5. Production Deployment Instructions

### Full-Stack Docker Compose Deployment

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your desired POSTGRES_PASSWORD, API_KEY, and optional AI provider keys
   ```

2. **Launch Stack**:
   ```bash
   docker compose up -d --build
   ```

3. **Verify Health**:
   ```bash
   # Backend API healthcheck
   curl -f http://localhost:8000/api/v1/health

   # Frontend application
   curl -I http://localhost:3000
   ```

4. **Run Migrations Manually (if not using container entrypoint)**:
   ```bash
   alembic upgrade head
   ```

5. **Stop Stack**:
   ```bash
   docker compose down -v
   ```

---

## 6. Session 25.2, 25.3 & 25.4 — Evaluation Integrity Closures & Verification Gate

All evaluation integrity blockers and budget safety mechanisms have been resolved and verified via regression tests:

### 1. RAG Completion Status & Response Integrity (`eval/rag/eval_rag.py`)
- **Status:** **CLOSED / VERIFIED**
- Separate tracking for `attempted_count`, `success_count`, `failed_count`, `skipped_count`, and `execution_coverage_percent`.
- Strict response validation: responses from `answer_repository_question` must be dictionaries with a non-empty, non-whitespace string in `answer` and a list in `citations`. Malformed or empty responses fail closed, incrementing `failed_count`.
- Fails closed: never reports `COMPLETED` if any question fails, is malformed, or is skipped. Uses distinct `PARTIAL` status for mixed results, `FAILED` if all attempted fail, and `BLOCKED` if execution cannot proceed.
- Regression tests in `tests/test_s25_eval_rag_integrity.py` verify 1 success + 1 failure (`PARTIAL`), all failures (`FAILED`), full success (`COMPLETED`), and malformed/empty responses treated as failures.

### 2. RAG Monetary Budget Gate & Accounting (`eval/rag/eval_rag.py`)
- **Status:** **CLOSED / VERIFIED**
- **Dual Budget Gate**:
  - **Pre-request estimation**: Checks whether `accumulated_cost_usd + single_query_est_cost > max_budget_usd` ($1.00 max cap) before dispatching any request, halting queries that would foreseeably exceed the budget.
  - **Post-request actual halt**: If actual usage on an executed query causes `accumulated_cost_usd >= max_budget_usd`, execution halts immediately without issuing any subsequent requests, marking `budget_exceeded: True` and `budget_exhausted: True`.
- **Honest Cost Basis**:
  - Distinguishes `actual` provider token usage from `estimated` token usage (word-count heuristics).
  - Resolves model-specific pricing (e.g. `gpt-4o-mini`, `gpt-4o`, `gemini-1.5-flash`, `gemini-1.5-pro`).
  - `budget_verified` is strictly `False` unless actual provider token metadata was returned for all executed queries and model pricing was exact.
- **Guarantee vs. Limitation Boundary**:
  - *Guarantee*: Pre-request estimation prevents issuing foreseeable over-budget requests, and post-request accounting strictly prevents issuing any further requests once the budget cap is reached.
  - *Limitation*: A single in-flight query's actual output length is bounded by the LLM's `max_tokens` configuration, meaning pre-request estimates cannot guarantee a sub-cent monetary cap if actual LLM response length exceeds the conservative estimate.

### 3. Blind Rating Integration & Deterministic Join (`eval/health/rating_sheet.py`, `eval/health/correlation.py`)
- **Status:** **CLOSED / VERIFIED**
- Algorithmic scores are kept strictly out of the reviewer-facing CSV (`eval/health/rating_sheet.csv`) to preserve double-blind integrity.
- Separate score export function `export_algorithmic_scores` provided in `rating_sheet.py`.
- Deterministic post-rating join implemented in `join_ratings_and_scores` keyed strictly by `(repo_url, commit_sha)`.
- Validates and rejects:
  - Duplicate keys in either ratings or scores CSVs (`test_join_rejects_duplicate_keys_*`).
  - Mismatched commit SHAs for the same repository URL (`test_join_rejects_mismatched_commit_sha`).
  - Unmatched rows between ratings and scores (`test_join_rejects_unmatched_rows`).
  - Missing, blank, non-numeric, or out-of-range algorithmic scores (`test_join_rejects_invalid_score`).
- Integration test `test_deterministic_join_valid_and_blind` verifies end-to-end blind workflow and correlation calculation.

### 4. Benchmark Candidate List Repaired (`eval/health/rating_sheet.py`, `eval/health/CANDIDATES.md`)
- **Status:** **CLOSED / VERIFIED**
- Replaced dead/placeholder URLs (such as `OWASP/BenchmarkUtils`) with the official `OWASP-Benchmark/BenchmarkJava`.
- Pinned and verified real, accessible full 40-character commit SHAs across all 15 repositories using `git ls-remote`.
- Verification evidence saved in `docs/s25_evidence/candidate_sha_verification.txt`.
- Stripped all quality hints (e.g. `(High)`, `(Medium)`, `(Low)`) from the reviewer-facing candidate list and CSV.

### 5. Sensitivity Analysis Clarified (`eval/health/sensitivity.py`)
- **Status:** **CLOSED / VERIFIED**
- Formally labeled output as **Composite-Score Drift Analysis (Component Weight Volatility)**.
- Clarified that it analyzes single-profile composite drift and does NOT measure cohort ranking stability across multiple repositories.
- Production weights (`DEFAULT_WEIGHTS_V2`) remain untouched.

### Summary Verification Status Table

| Area | Code / Harness Status | Empirical Evaluation Status | Notes |
| :--- | :--- | :--- | :--- |
| **RAG Evaluation** | **PASSED** (Response validation & dual budget gate verified) | **NOT RUN** (Pending live LLM provider keys & indexed runs) | Fails closed with `BLOCKED`/`NOT RUN`/`PARTIAL` |
| **Health Correlation** | **PASSED** (Blind sheet, deterministic join & quorum enforced) | **NOT RUN** (Pending human blind ratings) | $n=0$ reviewed, requires $n \ge 15$ |
| **Benchmark Candidates** | **PASSED** (All 15 SHAs verified via `git ls-remote`) | **N/A** (Dataset definition complete) | Evidence in `docs/s25_evidence/candidate_sha_verification.txt` |
| **Sensitivity Analysis** | **PASSED** (Explicitly labeled as composite drift) | **N/A** (Deterministic analysis) | Production weights preserved |
| **Graph Precision/Recall** | **PASSED** (Recall None without FN markers; Wilson CI) | **NOT RUN** (Pending human edge labels) | Double-blind sample sheets ready |



