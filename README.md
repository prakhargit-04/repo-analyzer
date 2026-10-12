# GitHub Repository Analyzer — Multi-Language Intelligence Pipeline

A real, tested implementation of a full repository analysis pipeline with
evidence-grounded AI question-answering, semantic search, and a Next.js
analysis dashboard.

**Verification status (be precise about what has and has not been checked):**
the backend and frontend test suites run offline and deterministically (see
*Running Tests*). Live-integration paths are NOT covered by the default suite:
real GitHub clones, the live Semgrep `--config auto` scan, and real
OpenAI / Gemini / sentence-transformers calls. See `REPORT.md` for the exact
list of what was and was not run for each release.

**Quick start:** `make setup && make verify` (see `make help`). `make verify` runs the backend suite twice consecutively, then frontend tests, type-check, lint, and repository hygiene checks; the production build is separate because Google Fonts require network access.

---

## Current Pipeline

```
GitHub repository URL
  ↓ Clone (git, HTTPS-only, exact SHA)
  ↓ Multi-language parsing (Python, Java, JS/TS — tree-sitter)
  ↓ Static analysis (radon CC/MI, bandit, semgrep, gitleaks, lizard)
  ↓ Knowledge graph construction (networkx — nodes, edges, call resolution)
  ↓ Health score (weighted composite: complexity, maintainability, security)
  ↓ Source chunking (deterministic line-range chunks + SHA provenance)
  ↓ Embedding generation (test: deterministic hash-derived vectors; real: configurable)
  ↓ Vector storage (JSON-serialised, run-scoped, linear cosine scan)
  ↓ Grounded RAG (retrieval → prompt → LLM → server-side citation validation)
  ↓ FastAPI + async worker + SQLite/PostgreSQL persistence
  ↓ Next.js dashboard (Overview, Findings, Files, Semantic Search, AI Assistant)
```

## Pipeline Components & Features

| Component | Description | Status |
|---|---|---|
| Ingestion & Parsing | Git clone (HTTPS-only), multi-language AST parsing (Python, Java, JS/TS via tree-sitter) | ✅ Complete |
| Static Analysis | Integrated security & complexity analysis (Radon CC/MI, Bandit, Semgrep, Gitleaks, Lizard) | ✅ Complete |
| Knowledge Graph | Code entity nodes, dependency import edges, heuristic call resolution, graph export | ✅ Complete |
| Persistence & API | SQLite/PostgreSQL persistence (SQLAlchemy + Alembic), FastAPI REST API, async worker | ✅ Complete |
| Dashboard UI | Next.js dashboard (Overview, Findings, Files, Graph, Semantic Search, AI Assistant) | ✅ Complete |
| Source Chunking | Deterministic line-range source chunking with SHA provenance tracking | ✅ Complete |
| Vector Retrieval | Run-scoped vector embeddings, similarity search, chunk retrieval API | ✅ Complete |
| Grounded RAG | Evidence-grounded question-answering with server-side citation validation | ✅ Complete |
| Security Hardening | Restricted CORS, strict GitHub HTTPS URL validator, sanitized error responses | ✅ Complete |
| Real Provider Integration | Provider factory wiring (sentence_transformers, OpenAI, Gemini), fail-fast validation | ⚠️ Fail-fast wiring complete / live validation pending |

## Known Limitations

- **Vector search is a linear scan** — embeddings are stored as JSON in SQLite and compared with cosine similarity in Python. No pgvector, no ANN index. Performance degrades with large repositories.
- **Call resolution is heuristic** — same-file function-name matching, not full Python scope resolution. Labeled `high_confidence`/`low_confidence`/`flagged` (never `certain`).
- **Test mode answers are placeholders** — with default providers (`LLM_PROVIDER=test`), AI answers are deterministic fixed strings. Real AI requires configuring a provider (see [docs/ai-modes.md](docs/ai-modes.md)). Test embeddings are deterministic hash-derived vectors (not semantic).
- **API accepts GitHub HTTPS repos only** — local paths, SSH URLs, non-GitHub hosts, and HTTP are rejected at the API layer. The CLI (`pipeline/main.py`) still accepts local paths.
- **Not hardened for production traffic** — single-process in-memory rate-limiter and API-key auth are implemented but no multi-tenant isolation, no horizontal scaling, no external auth provider.
- **Citation validation checks evidence IDs only** — verifies citation IDs exist in retrieved evidence, not natural language claim correctness.


---

## Quick Start

### Backend

```bash
pip install -r requirements.txt

# Optional: create .env from template
cp .env.example .env

# Run migrations (creates DB automatically)
alembic upgrade head

# Start API server
uvicorn pipeline.api.app:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000), submit a GitHub repository URL, and explore the dashboard.

### CLI (local-path mode, for development)

```bash
python pipeline/main.py --repo-url https://github.com/pytest-dev/iniconfig
# or
python pipeline/main.py --local-path /path/to/already/cloned/repo
```

---

## Test Mode vs Real Mode

### TEST MODE (default — offline, deterministic, CI-safe)

Default when no provider env vars are set:

```bash
LLM_PROVIDER=test        # Fixed placeholder answers, no API calls
EMBEDDING_PROVIDER=test  # Deterministic hash-derived vectors, no model download
```

In test mode:
- The AI Assistant returns a fixed placeholder answer referencing evidence chunks.
- Semantic Search returns chunks ranked by deterministic similarity scores in test mode; these vectors are not semantic embeddings.
- No API keys are needed; a few tests clone from GitHub and need network access.
- This verifies **plumbing only** (endpoint wiring, citation resolution, DB round-trips).

### REAL MODE (requires network + API keys)

To use real AI features, set env vars (copy `.env.example` → `.env`):

```bash
# Option A: Google Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

# Option B: OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=your_key_here

# Real embedding model (sentence-transformers, runs locally)
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2
```

> **Note:** Real provider packages (`sentence-transformers`, `openai`, `google-generativeai`) are optional and listed in `requirements-optional.txt`. Install only what you need: `pip install sentence-transformers` for local embeddings, or `pip install openai` / `pip install google-generativeai` for cloud LLMs.

---

## Running Tests

```bash
# Backend
pip install -r requirements.txt
python -m pytest tests/ -v

# Frontend
npm --prefix frontend test
```

### The default backend suite is hermetic (no network)

`pytest` runs Semgrep with the pinned local rules in `tests/semgrep_rules/test-rules.yml`
(`tests/conftest.py` sets `SEMGREP_CONFIG` for every non-`network` test), so it needs no
access to semgrep.dev and finishes in about 1.5 minutes on a laptop. `semgrep` must be
installed (`pip install -r requirements.txt`); the hermetic Semgrep tests fail loudly if it is
missing rather than skipping.

Opt-in markers, excluded by default (`pytest.ini`):

```bash
python -m pytest tests/ -m network    # real git clones + the live Semgrep `--config auto` scan
python -m pytest tests/ -m live_ai    # real OpenAI / Gemini / sentence-transformers (needs keys)
```

A deselected or skipped live test is **not** evidence that the live integration works.
Tests that need API keys (9 at the time of writing) are skipped when no key is set.

**Required tools for full static analysis (optional for unit tests):**
- `semgrep` — installed via pip (included in requirements.txt)
- `gitleaks` — separate Go binary; if absent, gitleaks analyzer reports `status: "unavailable"` (not `failed`)
- `bandit` — installed via pip (included in requirements.txt)

---

### Verification extras (0.24.7)

```bash
# Equivalence + timing of the graph builder vs the faithful original (~2,000 functions in the middle scale)
python scripts/bench_graph_large.py --runs 7
# Persistence cost on real pipeline output (asserts row counts, so it can never time an empty write)
python scripts/bench_persist.py --runs 5

# Real-provider AI smoke test (OPT-IN; needs internet, an API key and `pip install sentence-transformers openai`)
EMBEDDING_PROVIDER=sentence_transformers LLM_PROVIDER=openai OPENAI_API_KEY=... \
  python -m pytest tests/test_live_ai_smoke.py -m live_ai -s
# -> fails with "BLOCKED: ..." if a prerequisite is missing; writes a sanitized artifact to eval/results/live_smoke/

# Retrieval evaluation. With EMBEDDING_PROVIDER unset / `test` the numbers are PLUMBING DIAGNOSTICS, not quality.
python -m eval.run_retrieval_eval --embedding-provider test --k 1,3,5,10
```

The 20 evaluation labels are marked `reviewed` by the *assistant* that drafted them. An independent
second review has **not** happened; `docs/archive/REVIEW_PACKET.md` has what a reviewer needs. Until then every
metric is exploratory.

### Failure-state behaviour (what the API promises)

* A failed analyzer or embedding stage is never cached; a retry re-runs it.
* A `partial` run is reported as `partial` everywhere, including on a cache hit.
* A run with chunks but no embeddings answers `/retrieve` and `/ask` with HTTP 409, never an empty 200.
* The health score always says which components were not measured (`components_scored`, `reduced_component_set`, `note`).
* Database and file cache paths use the same SHA-256 analysis-configuration fingerprint: cache schema, analyzer version, source chunker version, embedding pipeline/provider/model/version, and the effective Semgrep ruleset identity. Local rules are fingerprinted by content, not absolute path. A legacy database run with a NULL fingerprint is recomputed once.
* `POST /api/v1/analyses` accepts optional `force_refresh: true` to skip the database cache short-circuit and file-cache read, then persist a new run. A healthy forced result is still written to the file cache. Older runs are retained; normal lookups continue preferring complete results over partial results, newest first. If an active job already exists for the same repository and commit, that job is returned rather than spawning a duplicate.
* The fingerprint is computed at persistence time; this assumes relevant configuration does not change between pipeline execution and persistence in the worker process.

Example forced refresh request:

```bash
curl -X POST http://localhost:8000/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"repo_url":"https://github.com/pytest-dev/iniconfig","force_refresh":true}'
```

A force-refresh request bypasses caches, but an already-active job for the same repository/commit is returned to avoid duplicate work.

### Clone hardening (0.24.5; verified in 0.24.7)

Every `git` call on an untrusted repository runs with hooks disabled
(`core.hooksPath=/dev/null`), `ext::` transports disabled, **HTTP redirects
rejected** (`http.followRedirects=false`; a renamed/moved repo now fails with a
clear error instead of being followed to another host), submodules never
fetched, and credential prompts disabled. A clone without a pinned commit is
shallow (`--depth 1`); a pinned commit keeps full history so it can be checked out.

## Security Notes (S22)

### Runtime hardening environment variables

- `API_KEY`: optional server-side API key; clients send it as `X-API-Key`.
- `RATE_LIMIT_RPM`: per-key (or per-client-IP) POST budget; `0` disables it.
- `TRUST_PROXY_HEADERS=1`: trust the first `X-Forwarded-For` hop only behind a trusted proxy.
- `MAX_ACTIVE_JOBS`, `JOB_STALE_SECONDS`: queue capacity and stale-job cleanup controls.
- `SEMGREP_CONFIG`: Semgrep rules source. Unset or `auto` (default) uses the Semgrep-managed ruleset (needs network). Otherwise an **absolute path to a local rules file/directory outside the scanned repo**; registry packs, URLs, relative paths and rules inside the scanned repository are rejected (the scan then reports `failed`, never a clean result). Used by the test suite to stay offline.
- `REPO_MAX_MB`: clone-size limit (`0` disables it); `CACHE_MAX_AGE_DAYS` and `CACHE_MAX_MB` control cache cleanup.

- **CORS**: No wildcard (`*`) — origins are env-configurable via `CORS_ALLOWED_ORIGINS`. Default: `http://localhost:3000` (dev only). Production must set this explicitly.
- **URL validation**: The API submission endpoint (`POST /api/v1/analyses`) enforces GitHub-HTTPS-only URLs. Rejected: `http://`, `git@`, `file://`, local paths, localhost/private IPs, userinfo tricks, non-default ports, extra path segments, query strings, fragments, option-injection prefixes (`-`).
- **No secrets committed** — `.env` is gitignored. Use `.env.example` as the template.
- **Error responses** do not leak internal paths or stack traces (global exception handler in `app.py`).

---

## Architecture: Deterministic vs AI Boundary

Every knowledge graph node/edge carries a `provenance` field naming the exact
tool or heuristic that produced it:

- Structural edges (containment, imports): `confidence: structural_certain` — direct AST facts
- Call edges: `high_confidence` / `low_confidence` / `flagged` — name-matching heuristic, not scope resolution
- Finding nodes: bandit/semgrep/gitleaks provenance with exact tool version
- RAG answers: every claim traces back to a cited `SourceChunk` with exact file + line range + commit SHA. Server-side citation validator strips any LLM citation not backed by a retrieved chunk.

---

## Real Bugs This Pipeline Found (Methodology Validation)

1. Bandit noise from test asserts (B101) — fixed by shared `is_test_file` filter
2. Test exclusion rule incomplete (`testing/`, `conftest.py` not matched) — found on `iniconfig`
3. Local-path caching was silently unsound (placeholder cache key) — fixed with real content hash
4. Tool failure could produce fake 100 security score — now reports `status: "failed"`
5. Call-confidence labels overclaiming `"certain"` — relabeled to `"high_confidence"` etc.
6. Provenance captured fake versions — now real `radon.__version__` / `importlib.metadata`
7. `weights_used` reported un-renormalized weights — fixed
8. Duplicate same-file function names silently colliding in call resolution — fixed
9. Bandit non-zero-but-not-crash exit codes not distinguished — fixed
10. Documentation drift in confidence-label names — fixed
11. Local-path snapshot hashing was metadata-hash, not content-hash — fixed
12. Cache key didn't include analyzer version — fixed with `CACHE_SCHEMA_VERSION` + `ANALYZER_VERSION`
13. Bandit exit code never checked — fixed, only codes 0/1 accepted
14. `"partial"` component with a number was reported as `"complete"` overall — fixed

All 14 bugs have permanent regression tests in `tests/test_regression.py`.
