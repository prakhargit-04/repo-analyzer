"""
FastAPI application entrypoint for Repo Analyzer (S15, updated S22).
"""
from __future__ import annotations
import os
import sys
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from db.engine import get_engine, create_all_tables
from api.routes import router as api_router

logger = logging.getLogger("repo_analyzer_api")


from contextlib import asynccontextmanager
from db.store import cleanup_stale_jobs
from util import cleanup_cache, get_cache_dir


def _optional_nonnegative_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
        if value < 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning("Invalid %s; ignoring cache cleanup setting", name)
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = os.environ.get("DATABASE_URL", "sqlite:///repo_analyzer.db")
    try:
        engine = get_engine(db_url)
        create_all_tables(engine)
        stale_count = cleanup_stale_jobs(engine)
        if stale_count > 0:
            logger.info(f"Marked {stale_count} stale jobs as failed on startup.")
        max_age, max_mb = _optional_nonnegative_int("CACHE_MAX_AGE_DAYS"), _optional_nonnegative_int("CACHE_MAX_MB")
        if max_age is not None or max_mb is not None:
            cleanup_cache(get_cache_dir(), max_age, max_mb)
    except Exception as exc:
        logger.warning(f"Could not initialize database on startup: {exc}")
    yield


def _get_cors_origins() -> list[str]:
    """
    Build the CORS allowed origins list from environment.

    CORS_ALLOWED_ORIGINS (env var): comma-separated list of allowed origins.
    Default: http://localhost:3000 and http://127.0.0.1:3000 for local dev.

    Production deployments MUST set CORS_ALLOWED_ORIGINS to an explicit,
    restrictive list. The wildcard "*" is intentionally never allowed here
    because allow_credentials=True + "*" is a security misconfiguration.
    """
    env_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if env_origins:
        origins = [o.strip() for o in env_origins.split(",") if o.strip() and o.strip() != "*"]
        if not origins:
            origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    else:
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    return origins


from version import APP_VERSION

def create_app() -> FastAPI:
    app = FastAPI(
        title="Repo Analyzer API",
        description="Language-agnostic repository analysis and knowledge-graph engine backend",
        version=APP_VERSION,
        docs_url="/docs",

        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    from api.security import APIKeyMiddleware
    from api.rate_limit import RateLimitMiddleware
    # Starlette middleware registration is LIFO (last added = outermost).
    # Desired request flow (outermost -> innermost):
    # CORSMiddleware -> APIKeyMiddleware -> RateLimitMiddleware
    # Therefore we add RateLimit first, APIKey second, CORS last.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(APIKeyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # Global unhandled exception handler to prevent leaking internal traces or file paths
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled server exception on {request.url}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal Server Error",
                "detail": "An internal server error occurred while processing the request.",
            },
        )

    app.include_router(api_router)
    return app



app = create_app()
