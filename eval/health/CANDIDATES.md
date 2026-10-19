# Health Score Validation Benchmark Candidates

Proposed panel of 15 public repositories across three quality tiers and distinct architectural domains for empirical health score validation.

## Candidate Repository Panel & Verified Pinned Commits

This panel represents 15 public open-source repositories selected across distinct software architectures for empirical health-score validation.

> [!NOTE]
> **Double-Blind Rating Protocol**: The study design stratification tiers below are maintained strictly for balanced sampling and are intentionally **omitted** from the reviewer rating sheet (`eval/health/rating_sheet.csv`). Human reviewers evaluate repositories blind to both quality tiers and algorithmic scores.
> Human validation has **not** yet been conducted; empirical validation will be evaluated only when blind ratings have been collected and verified.

| Repository | Verified Pinned SHA | Language / Domain | Study Design Stratification |
| :--- | :--- | :--- | :--- |
| [`pytest-dev/iniconfig`](https://github.com/pytest-dev/iniconfig) | `93f5930e668c0d1ddf4597e38dd0dea4e2665e7a` | Python / CLI Configuration Parsing | Tier 1 (High Quality Baseline) |
| [`pallets/itsdangerous`](https://github.com/pallets/itsdangerous) | `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd` | Python / Cryptographic Data Signing | Tier 1 (High Quality Baseline) |
| [`psf/requests`](https://github.com/psf/requests) | `0e322af87745eff34caffe4df68456ebc20d9068` | Python / HTTP Client Library | Tier 1 (High Quality Baseline) |
| [`urllib3/urllib3`](https://github.com/urllib3/urllib3) | `27e2a5c5a7ab6a517252cc8dcef3ffa6ffb8f61a` | Python / HTTP Networking & Connection Pooling | Tier 1 (High Quality Baseline) |
| [`bottlepy/bottle`](https://github.com/bottlepy/bottle) | `ab49e0c22491f8acfcb02e4a7b8c648843268233` | Python / Web Microframework | Tier 1 (High Quality Baseline) |
| [`pallets/flask`](https://github.com/pallets/flask) | `c12a5d874c5a014495eb2db8a73f40037bc813ac` | Python / Web Application Framework | Tier 2 (Moderate Complexity) |
| [`marshmallow-code/marshmallow`](https://github.com/marshmallow-code/marshmallow) | `b9646e326c511c11fc07aef4aa0004c14a5d454c` | Python / Object Serialization & Validation | Tier 2 (Moderate Complexity) |
| [`pallets/click`](https://github.com/pallets/click) | `874ca2bc1c30d93a4ac6e36a15ed685eafe89097` | Python / Command Line Interface Toolkit | Tier 2 (Moderate Complexity) |
| [`pallets/werkzeug`](https://github.com/pallets/werkzeug) | `f9995e967979eb694d6b31536cc65314fd7e9c8c` | Python / WSGI Web Application Utility | Tier 2 (Moderate Complexity) |
| [`encode/httpx`](https://github.com/encode/httpx) | `326b9431c761e1ef1e00b9f760d1f654c8db48c6` | Python / Async HTTP Client | Tier 2 (Moderate Complexity) |
| [`OWASP/NodeGoat`](https://github.com/OWASP/NodeGoat) | `c5cb68a7084e4ae7dcc60e6a98768720a81841e8` | JavaScript / Vulnerable Node.js App | Tier 3 (Intentionally Insecure) |
| [`OWASP-Benchmark/BenchmarkJava`](https://github.com/OWASP-Benchmark/BenchmarkJava) | `bc5ffeb09fb18ab039806d84ca1f718c2e332c54` | Java / Static Analysis Benchmark | Tier 3 (Intentionally Insecure) |
| [`juice-shop/juice-shop`](https://github.com/juice-shop/juice-shop) | `39b46860612990ae18d499a20472172839fe8c77` | JS / TS / OWASP Benchmark | Tier 3 (Intentionally Insecure) |
| [`vulhub/vulhub`](https://github.com/vulhub/vulhub) | `9b90d4276f84feed6333286afeb7e1250379a1da` | Multi / Vulnerability Recipes | Tier 3 (Intentionally Insecure) |
| [`WebGoat/WebGoat`](https://github.com/WebGoat/WebGoat) | `5357a65e054976cd7d79b81ef3906ded050ed921` | Java / Deliberate Flaws Training App | Tier 3 (Intentionally Insecure) |

---

## Dry-Run Health Scores on Benchmark Repositories (Part A Evidence)

Measured using `scripts/explain_score.py` calling production `compute_health_score`:

| Repository | Status | Composite Score | Components Scored | Key Factors |
| :--- | :--- | :--- | :--- | :--- |
| **`pytest-dev/iniconfig`** | `success` | **84.44** | `maintainability` (100.0), `complexity` (100.0), `security` (88.0), `dependencies` (30.0) | High maintainability and low complexity; lowered by OSV dependency checks. |
| **`pallets/itsdangerous`** | `success` | **95.51** | `maintainability` (100.0), `complexity` (92.9), `security` (90.0), `dependencies` (100.0) | Pristine mature library; high scores across all four analyzers. |
| **`.` (Local Repo)** | `partial` | **52.11** | `maintainability` (92.6), `complexity` (79.9), `security` (0.0) [`dependencies`: unavailable] | Reduced component set; Bandit/Semgrep rule triggers in test suites zeroed security subscore. |
