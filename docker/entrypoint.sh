#!/bin/sh
set -e

# Normalize postgresql:// to postgresql+psycopg2:// for SQLAlchemy 2.x psycopg2 compatibility
if [ -n "$DATABASE_URL" ]; then
    case "$DATABASE_URL" in
        postgresql://*)
            DATABASE_URL="postgresql+psycopg2://${DATABASE_URL#postgresql://}"
            export DATABASE_URL
            ;;
    esac
fi

echo "[entrypoint] Waiting for database if configured..."
if [ -n "$DATABASE_URL" ] && echo "$DATABASE_URL" | grep -q "postgres"; then
    echo "[entrypoint] PostgreSQL configured; waiting for connection..."
    # Simple retry loop for database connectivity
    max_retries=30
    count=0
    until python -c "
import sys, os
from sqlalchemy import create_engine, select
url = os.environ.get('DATABASE_URL')
try:
    engine = create_engine(url, connect_args={'connect_timeout': 3})
    with engine.connect() as conn:
        conn.execute(select(1))
    sys.exit(0)
except Exception:
    sys.exit(1)
" >/dev/null 2>&1; do
        count=$((count + 1))
        if [ "$count" -ge "$max_retries" ]; then
            echo "[entrypoint] ERROR: Timed out waiting for database at $DATABASE_URL" >&2
            exit 1
        fi
        echo "[entrypoint] Database not ready yet ($count/$max_retries)..."
        sleep 2
    done
    echo "[entrypoint] Database is reachable."
fi

echo "[entrypoint] Running Alembic migrations (upgrade head)..."
python -m alembic upgrade head

echo "[entrypoint] Migrations completed successfully. Starting Uvicorn server..."
exec uvicorn pipeline.api.app:app --host 0.0.0.0 --port 8000
