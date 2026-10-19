# ── Stage 1: Build dependencies ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for compiling C-extensions (tree-sitter, psycopg2), git, and download tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git libpq-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install pinned Gitleaks binary with checksum verification
ENV GITLEAKS_VERSION=8.21.2
ENV GITLEAKS_SHA256=5bc41815076e6ed6ef8fbecc9d9b75bcae31f39029ceb55da08086315316e3ba
RUN curl -fsSL -o gitleaks.tar.gz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
    && echo "${GITLEAKS_SHA256}  gitleaks.tar.gz" | sha256sum -c - \
    && tar -xzf gitleaks.tar.gz gitleaks \
    && mv gitleaks /usr/local/bin/gitleaks \
    && chmod +x /usr/local/bin/gitleaks \
    && rm gitleaks.tar.gz

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system libraries: git, curl (for HEALTHCHECK), libpq5 (for PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages and gitleaks binary from builder
COPY --from=builder /install /usr/local
COPY --from=builder /usr/local/bin/gitleaks /usr/local/bin/gitleaks

# Copy Alembic config and migrations
COPY alembic.ini ./
COPY pipeline/ ./pipeline/
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Non-root user for container security
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

# Expose backend port
EXPOSE 8000

# Default environment configuration
ENV DATABASE_URL=sqlite:///./repo_analyzer.db
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Container healthcheck
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
