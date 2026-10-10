# Changelog

All notable changes to Repo Analyzer will be documented in this file.

## [0.24.2] - 2026-10-10

### Fixed (correctness bugs guarded by new tests)
- **R1 — Exception Layering**: `ask_repository_question_route` now catches `EmbeddingMismatchError` and returns HTTP 409 (previously 500). Guarded by `test_ask_returns_409_on_dimension_mismatch`.
- **R2 — Frontend Proxy**: Fixed TypeScript TS2353 `duplex` error in `proxy.ts`; added strict header allowlist; path validator rejecting `../`, `%2e`, `%2f`, `%5c`, `%25`; `X-API-Key` server-side injection; `X-Forwarded-For` first-hop only. Guarded by `frontend/src/__tests__/proxy.test.ts` (67 tests).
- **R3 — Middleware Order & Rate-Limit Identity**: Corrected `add_middleware` registration order (RateLimit→APIKey→CORS, giving CORS outermost). Added `AUTH_FAIL_RPM` failed-auth rate-limiting bucket. Rate-limit key now scoped per `sha256(api_key):client_ip`. Guarded by `TestMiddlewareAndRateLimitHardening` in `test_s22_security.py`.
- **R4 — REPO_MAX_MB Guard**: Replaced `shutil.disk_usage` with `working_tree_size_bytes()` that walks the working tree, excludes `.git` at any depth, skips symlinks/sockets/unreadable files. Guarded by `TestRepoMaxMbHardening` in `test_ingestion_hardening.py`.
- **R5 — Single Cache Directory Definition**: Replaced three divergent hardcoded cache paths with `get_cache_dir()` in `util.py`; added `is_dangerous_cache_path()` safety guard. Guarded by `test_cache_hardening.py`.

### Added
- `tests/test_sql_reads_oracle.py` — deterministic SQL read ordering with `nulls_last`, parity vs in-memory oracle.
- `tests/test_graph_builder_oracle.py` — 400-seed differential parity test between optimized and linear-scan reference graph builder.
- `tests/test_retrieval_parity.py` — numpy vs pure-Python cosine similarity within 1e-9 tolerance, zero-vector edge case.
- `tests/test_rag_budget.py` — evidence block budget enforcement, contiguous citation tags, citation ID validator.
- `tests/test_migrations.py` — idempotent Alembic migrations; `0006_graph_read_indexes` safe on pre-existing DB.
- `tests/test_misc_guards.py` — `MAX_ACTIVE_JOBS` fallback to 50 on invalid input; `NON_FINAL_JOB_STATUSES` invariant; `cleanup_stale_jobs` targets only stale non-final jobs.
- `tests/test_repo_hygiene.py` — CI gate verifying no `.db`, `.pyc`, `__pycache__`, `.next`, `.tsbuildinfo` in repository.
- `scripts/bench.py` — reproducible benchmark script (>=5 runs, fixed seeds, prints median); results committed in `REPORT.md`.
- `scripts/check_repo_hygiene.py` — enforces zero forbidden build artifacts; `--clean` flag removes them.

### Changed
- Bumped `APP_VERSION` to `0.24.2`.
- CI `ci.yml`: fixed action tags (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`); added `pytest-timeout`; added hygiene check step; added `--timeout=120` to pytest runs.
- `REPORT.md` fully rewritten: removed unverified performance claims (`231x`, `80x`, `16x`, `37x`), removed incorrect test counts (`358 passed`), removed false `production-ready` claim; replaced with measured numbers from `scripts/bench.py`.
- `README.md` Known Limitations: corrected statement that API has no auth/rate-limiting (both are now implemented).

## [0.24.1] - 2026-10-10

- Hardened SQL graph/findings reads with deterministic ordering (`nulls_last`), SQL filters, and chunked edge lookups.
- Restored duplicate-class graph-builder semantics; added graph-read indexes (migration `0006`).
- Corrected CORS/auth/rate-limit middleware ordering; hardened token-bucket handling.
- Added NumPy dependency and float64/zero-norm retrieval parity handling.
- Added safe RAG evidence block budgeting.

## [0.24.0] - 2026-10-10

### Added
- Direct SQL Read Endpoints for summary, graph, findings, and files with pagination.
- Lizard non-Python complexity fallback for JavaScript, TypeScript, Java, C++.
- X-API-Key authentication middleware (optional, via `API_KEY` env var).
- Token Bucket Rate Limiting returning 429 + `Retry-After`.
- Backpressure capacity guard (`MAX_ACTIVE_JOBS`) returning 503.
- Vectorized cosine similarity using NumPy matrix operations.

### Fixed
- Knowledge Graph Summary Persistence: added `knowledge_graph_summary_json` column + Alembic migration `0005`.
- RAG Prompt Truncation: 12k char evidence budget, user question before and after evidence.
- Semgrep Severity Penalty: `HIGH`/`ERROR`=15, `WARNING`/`MEDIUM`=7, `INFO`/`LOW`=2.
- Embedding Model Lazy Loading in `build_cache_key`.
- Stuck Jobs Startup Cleanup via `cleanup_stale_jobs` in FastAPI lifespan.
- Retrieval Dimension Mismatch Contract → HTTP 409.
- Cache-Hit Notification Stage Text → "Loaded from file cache".
- Database Bulk Insert Flushing eliminated per-record flush calls.

### Changed
- Bumped `APP_VERSION` to `0.24.0`.
- Bumped `CACHE_SCHEMA_VERSION` to `v5`.
