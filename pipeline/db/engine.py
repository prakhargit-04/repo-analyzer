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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from .models import Base


_DEFAULT_SQLITE_URL = "sqlite:///repo_analyzer.db"


def get_default_url() -> str:
    """Return the DATABASE_URL from environment, falling back to a local SQLite file."""
    return os.environ.get("DATABASE_URL", _DEFAULT_SQLITE_URL)


def get_engine(url: str | None = None, **kwargs) -> Engine:
    """
    Create and return a SQLAlchemy Engine.

    For SQLite connections, enforce foreign key constraints (disabled by default
    in SQLite) and set WAL journal mode for better concurrency.
    """
    resolved_url = url or get_default_url()
    connect_args = {}

    if resolved_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine = create_engine(resolved_url, connect_args=connect_args, **kwargs)

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
    """Create all ORM-defined tables. Idempotent (uses checkfirst=True)."""
    Base.metadata.create_all(engine, checkfirst=True)


def drop_all_tables(engine: Engine) -> None:
    """Drop all ORM-defined tables. For testing / migration resets only."""
    Base.metadata.drop_all(engine)
