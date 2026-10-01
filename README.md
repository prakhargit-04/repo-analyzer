# GitHub Repository Analyzer — Multi-Language Intelligence Pipeline

A real, tested implementation of a full repository analysis pipeline with
evidence-grounded AI question-answering, semantic search, and a Next.js
analysis dashboard. Validated end-to-end against real GitHub repositories.

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
  ↓ Embedding generation (test: random unit vectors; real: configurable)
  ↓ Vector storage (JSON-serialised, run-scoped, linear cosine scan)
  ↓ Grounded RAG (retrieval → prompt → LLM → server-side citation validation)
  ↓ FastAPI + async worker + SQLite/PostgreSQL persistence
  ↓ Next.js dashboard (Overview, Findings, Files, Semantic Search, AI Assistant)
```

## What's Implemented

| Session | Feature | Status |
|---|---|---|
| S1–S13 | Python parsing, static analysis, knowledge graph, health score, caching | ✅ Complete |
| S14 | SQLite/PostgreSQL persistence (SQLAlchemy + Alembic) | ✅ Complete |
| S15 | FastAPI + async worker + job queue | ✅ Complete |
| S16 | Next.js dashboard (Overview, graph, findings) | ✅ Complete |
| S17–S18 | Analysis dashboard, files, evidence drilldown, end-to-end stabilization | ✅ Complete |
| S19 | Source content ingestion, deterministic evidence chunks, SourceChunk persistence | ✅ Complete |
| S20 | Embedding generation (with versioning), vector storage, repository-scoped retrieval | ✅ Complete |
| S21 | Evidence-grounded RAG pipeline: retrieval → grounded LLM → citation validation | ✅ Complete |
| S22 | Repo hygiene, docs, CORS security, GitHub-HTTPS-only URL validation, panel mounting | ✅ Complete |

## Known Limitations

- **Vector search is a linear scan** — embeddings are stored as JSON in SQLite and compared with cosine similarity in Python. No pgvector, no ANN index. Performance degrades with large repositories. (S23+ scope)
- **Call resolution is heuristic** — same-file function-name matching, not full Python scope resolution. Labeled `high_confidence`/`low_confidence`/`flagged` (never `certain`).
- **Test mode answers are placeholders** — with default providers (`LLM_PROVIDER=test`), AI answers are deterministic fixed strings. Real AI requires configuring a provider (see [Test Mode vs Real Mode](#test-mode-vs-real-mode)).
- **API accepts GitHub HTTPS repos only** — local paths, SSH URLs, non-GitHub hosts, and HTTP are rejected at the API layer. The CLI (`pipeline/main.py`) still accepts local paths.
- **Not production-ready** — no authentication, no rate limiting, no multi-tenant isolation, no horizontal scaling.

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
EMBEDDING_PROVIDER=test  # Random unit vectors, no model download
```

In test mode:
- The AI Assistant returns a fixed placeholder answer referencing evidence chunks.
- Semantic Search returns chunks ranked by random similarity scores.
- All tests pass offline without any API keys.
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

> **Note:** Real provider integration (installing provider packages, wiring them to the LLM/embedding abstraction) is Session 23. The current code ships the provider abstraction (`pipeline/rag/llm.py`) and test provider only.

---

## Running Tests

```bash
# Backend (217 tests)
pip install -r requirements.txt
python -m pytest tests/ -v

# Frontend (40 tests)
cd frontend
npm test
```

**Required tools for full static analysis (optional for unit tests):**
- `semgrep` — installed via pip (included in requirements.txt)
- `gitleaks` — separate Go binary; if absent, gitleaks analyzer reports `status: "unavailable"` (not `failed`)
- `bandit` — installed via pip (included in requirements.txt)

---

## Security Notes (S22)

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
