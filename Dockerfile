# ── Stage 1: Build dependencies ────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for tree-sitter, psycopg2, git clone
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Only runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY pipeline/ ./pipeline/

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

# Expose FastAPI port
EXPOSE 8000

# Database defaults to SQLite (override via DATABASE_URL env var)
ENV DATABASE_URL=sqlite:///./repo_analyzer.db
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run Alembic migrations then start uvicorn
CMD ["sh", "-c", "python -m alembic upgrade head 2>/dev/null || true && uvicorn pipeline.api.app:app --host 0.0.0.0 --port 8000"]
