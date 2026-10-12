# AI Modes & Configuration Guide (Session 23)

Repo Analyzer supports two operational modes for AI embeddings and RAG question-answering: **Test Mode** (default, offline, deterministic) and **Real Mode** (optional, live model execution).

---

## 1. Test Mode (Default)

- **Purpose**: Fast, offline, deterministic execution for local development, unit testing, and CI environments.
- **Behavior**:
  - **Embeddings**: Uses `TestEmbeddingProvider` (hash-derived 64-dimensional unit vectors using SHA-256). Requires zero network, zero GPU, and zero model downloads.
  - **LLM**: Uses `TestLLMProvider` (parses retrieved evidence tags `[E1]`, `[E2]` and generates deterministic, structured placeholder answers).
- **Default Status**: Active whenever `EMBEDDING_PROVIDER` and `LLM_PROVIDER` are unset or set to `test`.

---

## 2. Real Mode (Live Models)

- **Purpose**: Production semantic search and grounded AI question answering.
- **Prerequisites**:
  1. Install optional dependencies:
     ```bash
     pip install -r requirements-optional.txt
     ```
  2. Set environment variables in `.env`:
     ```env
     EMBEDDING_PROVIDER=sentence_transformers
     EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2

     LLM_PROVIDER=gemini        # or openai
     GEMINI_API_KEY=your_key_here
     ```

---

## 3. How to Verify Active AI Mode

### Backend Status Endpoint
Call `GET /api/v1/ai/status`:
```json
{
  "mode": "real",
  "embedding": {
    "provider": "sentence_transformers",
    "model": "all-MiniLM-L6-v2",
    "dimension": 384
  },
  "llm": {
    "provider": "gemini",
    "model": "gemini-1.5-flash"
  },
  "configured": true
}
```

If misconfigured (e.g. missing API key or package), the endpoint returns `mode: "error"` with `configured: false` and a sanitized error message (never HTTP 500).

### Frontend Badge
The analysis dashboard displays live AI mode badges:
- `AI Mode: Test` (Amber disclaimer shown)
- `AI Mode: Real (<provider>/<model>)` (No disclaimer)
- `AI Mode: Misconfigured`
- `AI Mode: Unknown`

---

## 4. Known Limitations & Truthfulness

1. **Linear Scan Retrieval**: Embeddings are stored as JSON in SQLite/PostgreSQL and compared using in-memory cosine similarity. No ANN index or pgvector is used.
2. **Citation Validation**: Server-side citation validation verifies that cited evidence IDs (`[E1]`) exist in retrieved chunks, but does not verify natural language truthfulness.
3. **Test Mode Vectors**: Hash-derived test embeddings are deterministic for testing, not semantic.
4. **Scoring Weights**: Composite health score weights are heuristic approximations.
5. **No Production Auth**: The API does not include user authentication, quotas, or rate limiting.
