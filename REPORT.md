# Repo Analyzer v0.24.7 — Final Verification Report (S24 close-out)

**Release decision: READY for review in test mode, with the limitations listed below.**
No feature work was done in this revision. Application version is unchanged (`pipeline/version.py` and `openapi.json` both say 0.24.7).

## 1. Evidence

All results in this section were **executed by the author of this report on a clean extraction of the final archive** (the archive minus this `REPORT.md`; see "Tree digest"). Environment: Linux, Python 3.12.3, Node v22.22.2, npm 10.9.7, dependencies installed from `requirements.txt` (exact versions in `requirements.lock`).

| Check | Command | Result |
|---|---|---|
| Backend suite, run 1 | `python -m pytest tests/ -q -p no:cacheprovider --timeout=120` | 910 passed, 9 skipped, 3 deselected, 0 failed |
| Backend suite, run 2 (consecutive) | same | 910 passed, 9 skipped, 3 deselected, 0 failed |
| Frontend install | `cd frontend && npm ci` | exit 0 |
| Frontend tests | `npm test` | 81 tests, 81 pass, 0 fail |
| Frontend type-check | `npm run typecheck` | exit 0 |
| Frontend lint | `npm run lint` | exit 0 |
| Python lint | `python -m pyflakes pipeline/main.py pipeline/parser_interface.py pipeline/graph_builder.py scripts/run_cache_mutation_checks.py` | clean |
| Repo hygiene (pristine extract, before any test run) | `python scripts/check_repo_hygiene.py` | clean |
| Mutation checks | `make mutation-checks` (= `python scripts/run_cache_mutation_checks.py`) | exit 0, all 4 mutations killed (table below) |

The 3 deselected backend tests are opt-in network/live tests defined by `pytest.ini`; the 9 skips are tests that require optional live providers or network.

### Cache mutation checks

Each mutation edits one source location in a **temporary copy** (the working tree is never modified). The harness asserts the target text occurs exactly once, requires the unmutated baseline to pass first, requires the *specific named tests* to fail, and rejects collection/import errors as false kills.

| Run | Source change | Tests failing | Required |
|---|---|---|---|
| Baseline (unmutated) | none | 0 (27 passed) | 0 |
| M1 | remove DB `config_fingerprint` comparison (`pipeline/db/store.py`) | 4 | 4 |
| M2a | `force_refresh` no longer bypasses the DB cache (`pipeline/api/routes.py`) | 3 | 3 |
| M2b | `force_refresh` no longer bypasses the file cache (`pipeline/worker.py`) | 2 | 2 |
| M3 | ignore Semgrep ruleset identity (`pipeline/util.py`) | 5 | 5 |

Focused test files: `test_cache_fingerprint.py`, `test_force_refresh.py`, `test_analysis_config_fingerprint_unit.py`, `test_cache_compatibility.py`. `make verify` now also runs these checks.

## 2. Not independently reproduced

Everything above ran in a single environment. **Not** run anywhere, and so not claimed:

- Real AI providers (OpenAI, Gemini, sentence-transformers) with live credentials; default test-mode providers return placeholder answers and hash-derived (non-semantic) embeddings.
- GitHub Actions (Linux and Windows jobs, including the new pyflakes step), PostgreSQL, live Semgrep `--config auto`, real GitHub clones.
- Frontend production build (`npm run build`, needs network for Google Fonts).
- Independent human review of the evaluation labels.
- Results in any second environment or on any other OS.

## 3. Changes in this revision

- `tests/test_url_trust_boundary.py`: route-coverage test now discovers routes from the OpenAPI schema (the previous `inspect.signature` approach found zero routes and asserted nothing) and fails if discovery is empty.
- `pipeline/parser_interface.py`: removed unused imports; compatibility re-exports kept and declared in `__all__`. `pipeline/graph_builder.py`: annotation-only `TYPE_CHECKING` import, one dead assignment removed. `pipeline/main.py`: one unused import removed. No behavior change.
- `.github/workflows/ci.yml` and `make check`: pyflakes on the core modules.
- `scripts/run_cache_mutation_checks.py` and `make mutation-checks` (also in `make verify`).
- Process documents moved to `docs/archive/` (including the previous report); `README.md` link updated.
- `requirements.txt` gains upper bounds; `requirements.lock` added; `CHANGELOG.md` updated.
- Unchanged and checked identical to the previous archive: `pipeline/db/migrations/` (revisions 0001–0008), `openapi.json` (also matches the live app's generated schema), `SCHEMA.md`, `alembic.ini`, all of `frontend/`.

## 4. Dependency lock

`requirements.lock` lists 85 pinned packages, generated with `pip freeze` in a Python 3.12 Linux virtualenv after `pip install -r requirements.txt` (test tools pytest, pytest-timeout and pyflakes excluded). Key pins: tree-sitter 0.21.3, tree-sitter-languages 1.10.2, semgrep 1.180.0, fastapi 0.141.1, SQLAlchemy 2.1.4, alembic 1.20.0, pydantic 2.14.1, numpy 2.5.4, networkx 3.7, radon 6.0.1, lizard 1.24.1, bandit 1.9.4, uvicorn 0.54.0, httpx 0.28.1, psycopg2-binary 2.9.13. It is platform-specific and should be regenerated after dependency changes. `tree_sitter` stays pinned at 0.21.3 because `tree_sitter_languages` 1.10.2 needs that API (the source of the `Language(path, name)` FutureWarning); moving off it means switching to per-language grammar packages.

## 5. Tree digest

SHA-256 over all files sorted by relative path, hashing `relative_path + NUL + file_bytes + NUL`, **excluding** `REPORT.md` and `docs/archive/`:

`efda747709f4a2a3bd18be620296ef115fdaac54ddf6c3bf0bb01423927bd3cd`  (182 files)

Because the report itself is excluded, this digest is unchanged by editing the report. The archive's own SHA-256 cannot be stored inside the archive and is given alongside the download.

## 6. Known limitations

Linear-scan vector search; heuristic call resolution; in-memory rate limiter and API-key auth only (not multi-tenant production hardened); citation validation checks evidence IDs, not claim correctness; remaining pyflakes warnings exist in other modules and tests (mostly unused imports) and are not gated in CI. Do not describe this build as production-ready.
