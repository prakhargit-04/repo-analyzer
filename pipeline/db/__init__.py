"""
pipeline.db -- Persistent storage layer for repository analyses.

Architecture:
- SQLAlchemy 2.x ORM (engine.py + models.py)
- Alembic migrations (migrations/)
- Store functions for upsert/retrieve (store.py)
- Configured via DATABASE_URL env var (PostgreSQL in prod, SQLite in tests/CI)
"""
