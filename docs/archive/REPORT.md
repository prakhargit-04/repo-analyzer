# Repo Analyzer v0.24.7 — Final surgical correctness pass

## Release decision: BLOCKED

This pass implemented the requested cache fingerprint and force-refresh changes and added URL trust-boundary regression tests. It is **not eligible for a READY decision** because the full backend suite and the route/worker integration tests could not be executed in this environment, the mandatory mutation checks were not run, and the clean frontend install could not complete. Do not describe this archive as fully verified or production-ready.

**Repository identity:** the supplied ZIP has no `.git`; there is no Git commit SHA, branch, or working-tree status to report. Tree SHA-256 (sorted relative path + NUL + file bytes + NUL; excludes this report and build/dependency artifacts): `62dc308e0059ce40b7d103f5a2bcec7a40852c0a9198f6043a7fbf566748dce7` (NOT a Git SHA). No commit or push was made.

**Environment:** Python 3.13.5, Node 22.16.0, npm 10.9.2. The environment lacked `tree_sitter_languages`, `radon`, `pytest-timeout`, and `pyflakes`. Package installation attempts could not reach the package index.

## Summary of changes

1. Added `analysis_config_fingerprint()` in `pipeline/util.py`. It hashes, in fixed order, the cache schema, analyzer version, source chunker version, embedding pipeline version, embedding provider/model/version identity, and effective Semgrep ruleset identity. `build_cache_key(snapshot_id)` now hashes `fingerprint + "\n" + snapshot_id`. The fingerprint reads configuration only; it does not instantiate a model or run Semgrep.
2. Persisted the fingerprint on each `AnalysisRun` and require exact fingerprint equality for database-cache reuse. Legacy rows with NULL fingerprints are not reused and are recomputed once.
3. Added optional strict boolean `force_refresh` to `POST /api/v1/analyses`. A forced job bypasses the database cache short-circuit, the file-cache read, and the worker's completed-run reuse shortcut; healthy results are still written to the file cache and old runs are retained. An active job for the same repo/commit is returned rather than duplicated.
4. Added Alembic migration `0008_analysis_config_fingerprint_force_refresh.py` and the `create_all` compatibility shim for both new columns.
5. Added cache-fingerprint, force-refresh, migration, and repository URL trust-boundary tests.
6. Updated OpenAPI, the TypeScript request type, README, changelog, schema documentation, and version to 0.24.7.

### Revision-number deviation

The supplied repository already uses Alembic revision `0007` for health-score formula versioning. Reusing or rewriting that revision would corrupt the migration history, so this pass adds revision `0008` with `down_revision = "0007"`. The supported downgrade is `0008 -> 0007`, preserving the existing health-score migration. The earlier request to use a new `0007` / downgrade `0007 -> 0006` is therefore intentionally not followed.

## Files changed and justification

| File | Justification |
|---|---|
| `pipeline/util.py` | Shared analysis-configuration fingerprint and file-cache key composition |
| `pipeline/db/models.py` | Nullable run fingerprint and non-null force-refresh job flag |
| `pipeline/db/engine.py` | Idempotent light-migration shim for pre-existing `create_all` databases |
| `pipeline/db/store.py` | Persist fingerprint and reject database-cache runs with a stale/missing fingerprint |
| `pipeline/main.py` | `use_cache=False` skips file-cache reads while retaining healthy cache writes |
| `pipeline/worker.py` | Propagate job force-refresh intent and skip completed-run reuse for forced jobs |
| `pipeline/api/routes.py` | Bypass the DB cache only when requested and persist force-refresh on the queued job |
| `pipeline/api/schemas.py` | Add optional strict boolean request field |
| `pipeline/db/migrations/versions/0008_analysis_config_fingerprint_force_refresh.py` | Additive, idempotent migration for the two columns |
| `pipeline/version.py` | Required version bump to 0.24.7 (necessary exception to the listed file allowlist) |
| `openapi.json` | Add optional `force_refresh` request field and update API version metadata |
| `frontend/src/types/api.ts` | Add the optional request field only; no UI changes |
| `tests/test_cache_fingerprint.py` | DB/file cache invalidation regression coverage |
| `tests/test_force_refresh.py` | Force-refresh API and worker behavior coverage |
| `tests/test_url_trust_boundary.py` | Guard route coverage and reject invalid URLs before clone/remote resolution |
| `tests/test_migration_0008.py` | Migration and create-all shim tests |
| `tests/test_analysis_config_fingerprint_unit.py` | Dependency-light fingerprint unit tests runnable in this environment |
| `README.md` | Document fingerprint compatibility, force-refresh behavior, and setup dependencies |
| `Makefile` | Include `pyflakes` in the one-command development setup, as required by the verification workflow |
| `CHANGELOG.md` | Record v0.24.7 changes and limitations |
| `SCHEMA.md` | Document persisted fingerprint and force-refresh fields |
| `REPORT.md` | Replace contradictory previous release claims with this pass's actual evidence |

No protected parser, chunker, static-analysis logic, health-score logic, graph builder/reference/benchmark, RAG implementation, embedding-provider implementation, clone implementation, URL validator, frontend UI, existing test file, prior migration, or evaluation labels/review files was edited. The only version bump outside the explicit file list is `pipeline/version.py`, required by the requested release version.

## Verification workflow correction

`make verify` previously invoked the backend suite only once, so it could not enforce release gate G1. The Makefile now runs `test-backend` twice consecutively, then frontend tests and the existing type-check/lint/hygiene checks. The workflow was dry-run inspected with `make -n verify`; it was not fully executed because the required Python packages and frontend dependencies could not be installed in this network-restricted environment.

## Verification table

| Command/check | Status | Evidence / limitation |
|---|---|---|
| Baseline `python -m pytest tests -p no:cacheprovider --timeout=120 -q -rs` | BLOCKED | `pytest-timeout` is absent; pytest rejected `--timeout=120` before test collection. |
| Initial targeted integration tests before implementation | BLOCKED | Test collection stopped on missing `tree_sitter_languages`; assertions did not execute, so the required pre-fix failing-test evidence could not be obtained. |
| `python -m pytest tests/test_analysis_config_fingerprint_unit.py tests/test_migration_0008.py -q` | PASS | 8 passed in 0.62 seconds on the final source tree. Covers fingerprint identity basics and migration upgrade/downgrade/create-all shim paths. |
| `python -m py_compile` on all changed Python modules/tests | PASS | All listed files compiled successfully. This is syntax validation, not behavioral validation. |
| Full backend `python -m pytest tests -p no:cacheprovider -q -rs` | BLOCKED | Collection stopped with 25 errors, principally missing `tree_sitter_languages` and `radon`; no full-suite totals were produced. |
| Direct `validate_github_url` check | PASS (manual check) | 14 invalid URL forms rejected and a valid GitHub HTTPS URL accepted. Route-level no-clone integration tests could not run because API import requires the missing parser dependency. |
| OpenAPI JSON/field check | PASS | JSON parses; `force_refresh` is an optional boolean, not a required field; info version is 0.24.7. Only the request schema and version metadata differ from the prior OpenAPI artifact. |
| Direct SQLAlchemy cache compatibility check | PASS (manual synthetic integration) | Persisted one synthetic run; same config hit, changing `EMBEDDING_MODEL_NAME` from model-A to model-B at the same provider returned no cache hit, and changing the local Semgrep rules contents returned no cache hit. This was a one-off script, not a pytest regression run. |
| `npm ci` | BLOCKED | Install did not complete; package registry/network access timed out. The partial `node_modules` directory was removed from the deliverable. |
| Frontend tests / typecheck / lint / build | NOT RUN | Dependencies could not be installed in this environment. |
| `python -m pyflakes ...` | NOT RUN | `pyflakes` is absent and package installation could not reach the index. |
| Backend suite twice in a row | NOT RUN | Full suite could not collect. |
| Mutation checks (fingerprint comparison, force-refresh bypass, Semgrep identity) | NOT RUN | Must be run in an environment with project dependencies. |
| Protected 403 graph parity tests and clone tests | NOT RUN in this pass | Protected files/tests were not edited, but the suite could not collect due missing dependencies. |
| Real-provider AI / live Semgrep / PostgreSQL / GitHub Actions / independent human evaluation review | NOT RUN / BLOCKED | No credentials/network/service access or independent human reviewer was available. |
| Unmocked frontend build | BLOCKED / NOT RUN | `npm ci` did not complete; no build claim is made. |

## Self-review

- **Filters after LIMIT:** no new filtering was added after a limited SQL query; the current-config fingerprint is applied in SQL before ordering/limit.
- **First/last/unique-match semantics:** complete runs still rank ahead of partial runs, newest first; the existing 20-candidate cap and embedding guards remain.
- **Swallowed exceptions:** the new fingerprint helper does not swallow provider identity errors; it preserves `ValueError`. Database lookup returns no cache hit for an unknown provider, while `build_cache_key` preserves its existing exception behavior.
- **Unbounded structures:** the fingerprint reads the configured rules file or rules directory contents, matching the existing ruleset identity helper; no new persistent unbounded collection was added.
- **Secrets/paths in messages:** no new API error messages expose secrets or local paths.
- **SQLite/PostgreSQL:** migration uses SQLAlchemy boolean defaults and nullable string columns; only SQLite migration execution was tested. PostgreSQL remains unverified.
- **Migration idempotency:** migration 0008 inspects columns before add/drop; create-all shim checks columns before adding. SQLite tests passed for empty, 0004, 0006, downgrade to 0007, and pre-existing 0007 schema shim paths.
- **API shape:** only the optional `force_refresh` request field was added; no response fields, routes, or status codes were changed. OpenAPI version metadata also changed to 0.24.7.
- **Environment parsing:** no new environment variable parsing was introduced.

## Remaining risks

1. The full backend suite and the new route/worker integration tests remain unverified in this environment. Install the exact dependencies and run the documented commands before treating this as releasable.
2. The mandatory test-first gate could not be completed: tests were written and attempted before implementation, but missing dependencies prevented assertion execution on the untouched code.
3. Mutation checks are still required to prove the three cache regressions are caught by the corresponding tests.
4. The fingerprint is computed at persistence time; correctness assumes the relevant configuration remains stable between pipeline execution and persistence in the worker process.
5. Alembic revision `0008` is used instead of `0007` because `0007` already exists and must remain immutable.
6. Real-provider AI quality, independent human review of the 20-question evaluation, live Semgrep, PostgreSQL, GitHub Actions, and the unmocked frontend build are not verified.

## Final decision

**BLOCKED** — targeted fingerprint and migration tests pass, but the required full suite, route/worker integration checks, mutation checks, and frontend validation could not be completed. Run the exact validation commands in a clean environment with the declared project dependencies before making a release claim.

No commit or push was made. The supplied archive has no `.git`; branch, commit SHA, and Git working-tree status cannot be reported.
