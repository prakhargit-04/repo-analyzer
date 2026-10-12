# Changelog

All notable changes to Repo Analyzer will be documented in this file.

## [0.24.7] - 2026-10-12 (final verification revision; no version bump)

### Fixed
- `test_every_route_accepting_repo_url_is_covered_by_validation_guard` discovered zero routes (FastAPI wraps endpoint signatures) and so asserted nothing; it now reads the OpenAPI schema and asserts discovery is non-empty.
- pyflakes findings in `parser_interface.py`, `main.py`, `graph_builder.py` (unused imports, undefined annotation names, one dead assignment). Compatibility re-exports in `parser_interface` are declared in `__all__`.

### Changed
- CI and `make check` run pyflakes on the three core modules.
- Process/session documents moved to `docs/archive/`; `REPORT.md` rewritten with measured results.
- `requirements.txt` has upper bounds; `requirements.lock` added. `tree_sitter` remains pinned (see file comment).
- Added `scripts/run_cache_mutation_checks.py` and `make mutation-checks` (also run by `make verify`).

## [0.24.7] - 2026-10-12 (initial)

### Fixed
- **Database cache compatibility now uses one analysis-configuration fingerprint.** The fingerprint includes cache schema, analyzer, source chunker, embedding pipeline/provider/model/version, and Semgrep ruleset identity. This closes the DB-cache gaps for model changes at the same vector dimension, chunker changes, and Semgrep ruleset edits. File-cache keys derive from the same fingerprint. Tests: `tests/test_cache_fingerprint.py`.
- **Legacy DB runs with no fingerprint are recomputed once.** The new nullable `analysis_runs.config_fingerprint` column is added by Alembic revision `0008` (revision `0007` already exists for health formula versioning and is not rewritten). The create_all compatibility shim adds the columns to pre-existing tables.
- **Added opt-in forced refresh.** `POST /api/v1/analyses` accepts optional `force_refresh: true`, bypassing the DB cache short-circuit and file-cache reads while still writing a healthy result. Existing active jobs are returned instead of duplicated; previous runs are retained. Tests: `tests/test_force_refresh.py`.
- **Repository URL trust boundary has regression coverage.** `tests/test_url_trust_boundary.py` checks every current route that accepts repository URLs and verifies invalid inputs are rejected before clone/remote resolution.

### Compatibility and limitations
- Fingerprints are computed when the worker persists the result; the configuration is assumed stable during a single job.
- Real-provider AI, independent human evaluation review, live Semgrep, PostgreSQL, GitHub Actions, and the unmocked font-dependent build remain unverified unless explicitly recorded as run in `REPORT.md`.

## [0.24.6] - 2026-10-11

Verification and failure-state pass. Every fix below has a test that FAILED on 0.24.5 (see `tests/test_v0246_failure_states.py`).

### Fixed
- **A failed embedding stage was reported as `completed`** (detail text said "failed" but the stage row said success). It is now `failed`; the job still finishes (embedding failure stays non-fatal). Test: `test_embedding_failure_is_reported_as_failed_stage`.
- **Unavailable embeddings looked like "no match"**: `/retrieve` returned HTTP 200 with zero results (and `/ask` fell through) when a run had chunks but no embeddings at all. New `EmbeddingsUnavailableError` (subclass of `EmbeddingMismatchError`) maps to HTTP 409 with an explicit message. A repository with no chunks is still a legitimate empty result. Tests: `test_unavailable_embeddings_are_not_an_empty_retrieval_result`, `test_repository_with_no_chunks_is_a_legitimate_empty_retrieval`.
- **A transient failure was memoised.** Results containing a *failed* analyzer or failed embeddings were written to the file cache and replayed for that commit. They are no longer cached (`unavailable`/`unsupported`/`partial` stay cacheable). Tests: `test_embedding_failure_is_not_memoised_so_a_retry_can_recover`, `test_degraded_retry_does_not_replace_a_better_run_and_better_replaces_degraded`.
- **A retry could not recover, and a degraded run could win.** `find_completed_run_by_sha` now prefers a `complete` run over a `partial` one, never reuses a run whose embeddings are missing, and the worker persists a fresh result when it is better than the stored run.
- **A cache-hit job for a partial run was presented as `completed`.** It is now `partial`. Test: `test_cache_hit_of_partial_run_is_reported_partial_not_completed`.
- **The API dropped the reduced-component-set disclosure.** `components_scored`, `reduced_component_set` and `note` existed only on the pipeline result / file cache; the DB-backed API (the normal path) omitted them. They are now derived from the persisted sub-scores by one shared helper (`health_score.reduced_set_summary`). Test: `test_failed_security_scan_is_never_reported_clean`.
- **`cleanup_stale_jobs()` crashed with `NameError`** when called without an explicit threshold (`store.py` used `os` without importing it; latent since 0.24.2). Test: `test_stale_job_cleanup_default_threshold_reads_env`.

### Added
- `tests/test_graph_builder_full_parity.py` (403 tests): byte-for-byte equivalence of every edge type, **including `calls`**, against `tests/reference/graph_builder_original.py` (the verbatim pre-optimisation builder). Run against the 0.24.0 builder it fails on exactly the 134 of 400 seeds that builder got wrong.
- `scripts/bench_graph_large.py` (equivalence check, warm-up, alternating runs, raw timings) and `scripts/bench_persist.py` (real pipeline output, asserts row counts).
- `tests/test_live_ai_smoke.py`: opt-in (`-m live_ai`) real sentence-transformers + OpenAI/Gemini smoke test on a pinned commit; fails loudly with `BLOCKED: ...` when prerequisites are missing; never substitutes test providers.
- `eval/REVIEW_PACKET.md`: materials for the independent second reviewer. Question labels were NOT changed.

### Final refinement (same version, 0.24.6)
- **Clone failures leaked internals and gave no reason.** The job `error_message` was `str(CalledProcessError)`: the full git argv (hardening flags), the server's temporary checkout path and the URL, with no reason. It is now `Failed to clone repository '<url>': <reason>` where the reason is one of: repository not found/not accessible, requested commit not found, URL redirected (redirects are not followed), host unreachable, timed out, or `git exited with status N`. Credentials in a URL are redacted; unexpected exceptions report only their type. Tests: `tests/test_clone_error_messages.py` (6 failed before). Hook/redirect/submodule/shallow behaviour was verified and left unchanged.
- **The file-cache key ignored the Semgrep ruleset.** It now includes `semgrep_ruleset_identity()` (`auto`, or a content hash of the local rules file/directory). Tests: `tests/test_cache_compatibility.py`.
- **The DB cache hit ignored versions.** `find_completed_run_by_sha` matched only repo + commit, so after an upgrade or an embedding-provider change the old run was served as current and the 409 "re-run the analysis" advice could not be satisfied. Reuse now requires the current analyzer version, cache-schema version and (if embeddings exist) the current embedding provider and pipeline version. Limitation: the embedding *model name within one provider* is not stored per row (the file-cache key and the retrieval dimension check cover it). Existing runs from older versions are no longer reused and are simply recomputed.
- Test data corrected: `tests/test_api.py::test_cache_hit_short_circuit` persisted a run with `analyzer_version=0.15.0` / `cache_schema_version=v1.0.0` and expected a cache hit, i.e. it encoded the bug above. It now uses the current versions.

### Corrected claims (documentation)
- The earlier graph benchmark ("0.87x/0.96x, slower") compared production against `graph_builder_reference.py`, which implements a *different, simplified* call-resolution algorithm (412 vs 3,000 `calls` edges on the benchmark fixture). It was not a valid optimisation comparison. Against the faithful original the optimised builder is 1.8x / 2.8x / 6.4x faster at 500 / 2,000 / 8,000 functions with identical output. It is retained.
- The `scripts/bench.py` synthetic payload used keys (`graph`, `embeddings`) that `persist_analysis` does not read, so its persistence and SQL-read figures measured 200 chunks and **zero** embeddings, graph nodes and findings. Treat those numbers as invalid; use `scripts/bench_persist.py`.

## [0.24.5] - 2026-10-11

### Security
- **Clone hardening.** All git calls (clone, checkout, ls-remote) now use `http.followRedirects=false`, `submodule.recurse=false`, `--no-recurse-submodules`, `GIT_TERMINAL_PROMPT=0` and a no-op `GIT_ASKPASS`; clones without a pinned SHA are shallow (`--depth 1`). Tests (tests/test_v0245_hardening.py): `test_clone_command_is_hardened`, `test_pinned_sha_clone_keeps_history_needed_for_checkout`, `test_ls_remote_is_hardened_too`, `test_clone_is_really_shallow_without_sha`, and `test_redirect_to_another_host_is_rejected_and_never_followed` (real local HTTP servers: before the fix git followed the redirect).

### Added
- **`formula_version`** (`HEALTH_FORMULA_VERSION = "2.1"`) on the health score, persisted in `health_scores.formula_version` (Alembic `0007`, idempotent, plus the `create_all` self-heal), returned by the API, shown in the dashboard, documented in SCHEMA.md. Older rows return `null`; no version is invented. Tests: `test_health_score_carries_formula_version_in_every_shape`, `test_formula_version_is_persisted_and_returned_by_api`, `test_legacy_row_without_formula_version_is_not_given_a_made_up_one`, `test_pre_existing_database_gets_formula_version_column`, `test_alembic_0007_chains_from_0006`.
- **Commit A -> B cache tests** (`test_commit_a_then_b_never_reuses_stale_results`, `test_analyzer_or_embedding_change_invalidates_cache`). These PASSED on 0.24.4: invalidation was already correct; they are regression guards, not bug fixes.
- `Makefile` (`make setup`, `make verify`, `make test`, `make check`, `make build`, `make network-tests`).

### Changed
- README opening no longer claims "validated end-to-end against real GitHub repositories"; it states what the default suite does and does not cover.

## [0.24.4] - 2026-10-11

### Fixed
- **Default test suite required network access and hung offline.** Semgrep ran with `--config auto`, which downloads rules from semgrep.dev; without network every analysis waited out the 180 s timeout, so the suite could not complete. The suite now runs Semgrep with pinned local rules: 426 passed, 0 failed, about 95 s, with the network blocked (previously did not finish).

### Added
- `SEMGREP_CONFIG` setting (`auto` by default, behaviour unchanged). A non-`auto` value must be an absolute path to local rules outside the scanned repo; registry packs, URLs, relative paths and in-repo rules are rejected and the analyzer reports `failed`. Local rules also run with `--metrics=off --disable-version-check`.
- `tests/semgrep_rules/test-rules.yml`, `tests/fixtures/semgrep_vuln_repo/`, `tests/test_hermetic_semgrep.py` (13 tests, incl. an opt-in `network` test of the real `auto` scan) and an autouse fixture in `tests/conftest.py`.

## [0.24.3] - 2026-10-11

Gap-closure pass on 0.24.2. `CACHE_SCHEMA_VERSION` is now `v6` (cache file format changed).

### Fixed (each guarded by a test in `tests/test_v0243_gaps.py` that failed on 0.24.2)
- **Cache key ignored the embedding model**: changing `EMBEDDING_MODEL_NAME` reused a stale cache, and an unknown `EMBEDDING_PROVIDER` was silently accepted. The key is now built by `embeddings.embedding_cache_identity()` (config only, still never instantiates a provider; includes the model name; raises `ValueError` for unknown providers). Tests: `test_cache_key_changes_with_embedding_model_name`, `test_cache_key_rejects_unknown_provider_and_never_instantiates`.
- **Cache file bloat**: embedding vectors were written as indented float lists. They are now stored as base64 little-endian float64 (`vector_b64`), lossless, decoded on load; caches with plain `vector` lists still load. Tests: `test_cache_file_stores_vectors_compactly_and_losslessly`, `test_load_cache_still_accepts_legacy_list_vectors`, `test_cache_schema_version_bumped_for_format_change`.
- **Health score hid a reduced component set**: scores now carry `components_scored` and `reduced_component_set`, and `note` begins "Score computed from a reduced component set: N of M components (missing: ...)". The dashboard shows the same notice. Test: `test_health_score_states_reduced_component_set`; frontend: `HealthScorePanel` tests.
- **Five endpoints rebuilt the entire analysis just to answer "does this run exist"** (`/status`, `/chunks`, `/files/{path}`, `/retrieve`, `/ask` twice). They now use `run_exists()`, `get_run_status_db()` and `get_file_detail_db()` (indexed SQL). Tests: `test_cheap_endpoints_do_not_rebuild_full_analysis`, `test_cheap_endpoints_still_404_for_unknown_run`.
- **Stale "Tier 1 / Python-only MVP" docstring and CLI description** in `pipeline/main.py`. Test: `test_main_docstring_no_longer_claims_python_only`.
- **SCHEMA.md drift**: stale `v4` references and analyzer version corrected; cache history table added.

### Added
- Frontend: `ApiError` (status + `Retry-After`) and `PanelError`, so the Assistant and Semantic Search panels give specific messages for 409 / 422 / 429 / 503.
- Frontend: `src/__tests__/components.test.tsx` (13 tests): `StatsGrid` incl. missing summary, `HealthScorePanel` incl. reduced set, panel error states, API client error mapping.

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
