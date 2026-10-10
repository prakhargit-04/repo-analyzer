"""
SQLAlchemy engine bootstrap for the persistence layer.

DATABASE_URL environment variable controls the backend:
  - PostgreSQL (production): postgresql+psycopg2://user:pass@host:5432/dbname
  - SQLite (tests / CI / local dev): sqlite:///repo_analyzer.db or sqlite:///:memory:

The rest of the codebase (pipeline, analyzers) is completely unaware of this
module -- persistence is opt-in. If DATABASE_URL is not set the pipeline runs
exactly as before.
"""
from __future__ import annotations
import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from .models import Base


_DEFAULT_SQLITE_URL = "sqlite:///repo_analyzer.db"
logger = logging.getLogger(__name__)


def get_default_url() -> str:
    """Return the DATABASE_URL from environment, falling back to a local SQLite file."""
    return os.environ.get("DATABASE_URL", _DEFAULT_SQLITE_URL)


def get_engine(url: str | None = None, **kwargs) -> Engine:
    """
    Create and return a SQLAlchemy Engine.

    For SQLite connections, enforce foreign key constraints (disabled by default
    in SQLite) and set WAL journal mode for better concurrency.

    NullPool is used for SQLite so that every session gets a fresh physical
    connection with no prior transaction state.  This prevents cross-engine
    read isolation races: when multiple SQLAlchemy engines point at the same
    SQLite file (e.g. the app's get_db_session engine vs. the worker engine),
    QueuePool can hand out a connection whose WAL read snapshot predates a
    commit made by a sibling engine — making freshly-committed rows invisible.
    NullPool avoids this by never reusing connections across sessions.
    """
    from sqlalchemy.pool import NullPool, StaticPool  # local import to keep module-level deps minimal

    resolved_url = url or get_default_url()
    connect_args = {}

    if resolved_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        poolclass = StaticPool if ":memory:" in resolved_url else NullPool
        engine = create_engine(
            resolved_url,
            connect_args=connect_args,
            poolclass=poolclass,
            **kwargs,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    else:
        engine = create_engine(resolved_url, **kwargs)

    return engine


def get_session_factory(engine: Engine) -> sessionmaker:
    """Return a configured sessionmaker bound to the given engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def create_all_tables(engine: Engine) -> None:
    """Create all ORM-defined tables and perform light column migration if needed."""
    Base.metadata.create_all(engine, checkfirst=True)
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        if "analysis_runs" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("analysis_runs")]
            if "knowledge_graph_summary_json" not in cols:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE analysis_runs ADD COLUMN knowledge_graph_summary_json TEXT"))
    except Exception as exc:
        # SQLite reports this exact condition when a concurrent initializer
        # won the race.  Other failures must remain visible to callers.
        if "duplicate column name" in str(exc).lower() or "column already exists" in str(exc).lower():
            logger.warning("create_all compatibility migration skipped (%s)", type(exc).__name__)
        else:
            logger.warning("create_all compatibility migration failed (%s)", type(exc).__name__)
            raise


def drop_all_tables(engine: Engine) -> None:
    """Drop all ORM-defined tables. For testing / migration resets only."""
    Base.metadata.drop_all(engine)
