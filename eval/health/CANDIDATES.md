# Health Score Validation Benchmark Candidates

Proposed panel of 15 public repositories across three quality tiers and distinct architectural domains for empirical health score validation.

## Candidate Repository Panel

| Tier | Repository | Language / Domain | Expected Quality Characteristics |
| :--- | :--- | :--- | :--- |
| **High** | [`pytest-dev/iniconfig`](https://github.com/pytest-dev/iniconfig) | Python / CLI Config | Pure Python, comprehensive test suite, minimal cyclomatic complexity, zero dependencies. |
| **High** | [`pallets/itsdangerous`](https://github.com/pallets/itsdangerous) | Python / Web Security | High test coverage, clean type annotations, disciplined security boundaries. |
| **High** | [`psf/requests`](https://github.com/psf/requests) | Python / HTTP Client | Extremely mature, stable API surface, thorough regression suite. |
| **High** | [`urllib3/urllib3`](https://github.com/urllib3/urllib3) | Python / Networking | Rigorous connection lifecycle, high code quality, automated security audits. |
| **High** | [`bottlepy/bottle`](https://github.com/bottlepy/bottle) | Python / Web Microframework | Single-file pure Python, lightweight, minimal external surface. |
| **Medium** | [`pallets/flask`](https://github.com/pallets/flask) | Python / Web Framework | Moderate complexity, multiple extension hooks, layered routing abstractions. |
| **Medium** | [`marshmallow-code/marshmallow`](https://github.com/marshmallow-code/marshmallow) | Python / Serialization | Extensive inheritance hierarchy, dynamic metaclass schema validation. |
| **Medium** | [`pallets/click`](https://github.com/pallets/click) | Python / CLI Toolkit | Complex terminal handling and parameter parsing, large codebase surface. |
| **Medium** | [`pallets/werkzeug`](https://github.com/pallets/werkzeug) | Python / WSGI Utility | Legacy HTTP header parsing, complex routing trees, wide dependency ecosystem. |
| **Medium** | [`encode/httpx`](https://github.com/encode/httpx) | Python / Async HTTP | Modern async architecture, dual transport layer, moderate cyclomatic complexity. |
| **Low** | [`OWASP/NodeGoat`](https://github.com/OWASP/NodeGoat) | JavaScript / Vulnerable App | Intentionally vulnerable application containing known injection and session flaws. |
| **Low** | [`OWASP/BenchmarkUtils`](https://github.com/OWASP/BenchmarkUtils) | Java / Vulnerability Benchmark | Benchmark containing thousands of synthetic static analysis vulnerability patterns. |
| **Low** | [`juice-shop/juice-shop`](https://github.com/juice-shop/juice-shop) | JS / TS / OWASP Benchmark | Intentionally vulnerable modern web application spanning entire OWASP Top 10. |
| **Low** | [`vulhub/vulhub`](https://github.com/vulhub/vulhub) | Multi / Vulnerability Envs | Pre-built vulnerable environment recipes containing documented CVE targets. |
| **Low** | [`WebGoat/WebGoat`](https://github.com/WebGoat/WebGoat) | Java / Deliberate Flaws | Deliberately insecure training application maintained by OWASP. |

---

## Dry-Run Health Scores on Benchmark Repositories (Part A Evidence)

Measured using `scripts/explain_score.py` calling production `compute_health_score`:

| Repository | Status | Composite Score | Components Scored | Key Factors |
| :--- | :--- | :--- | :--- | :--- |
| **`pytest-dev/iniconfig`** | `success` | **84.44** | `maintainability` (100.0), `complexity` (100.0), `security` (88.0), `dependencies` (30.0) | High maintainability and low complexity; lowered by OSV dependency checks. |
| **`pallets/itsdangerous`** | `success` | **95.51** | `maintainability` (100.0), `complexity` (92.9), `security` (90.0), `dependencies` (100.0) | Pristine mature library; high scores across all four analyzers. |
| **`.` (Local Repo)** | `partial` | **52.11** | `maintainability` (92.6), `complexity` (79.9), `security` (0.0) [`dependencies`: unavailable] | Reduced component set; Bandit/Semgrep rule triggers in test suites zeroed security subscore. |
