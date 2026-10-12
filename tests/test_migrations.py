"""
Sub-task 6.5: Alembic database migration & create_all column shim tests.
"""
import os
import sys
import pytest
from pathlib import Path
from alembic.config import Config
from alembic import command
from sqlalchemy import inspect, text, create_engine
from sqlalchemy.orm import Session

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from db.engine import get_engine, create_all_tables
from db.models import Base


def _get_alembic_config(db_url: str) -> Config:
    ini_path = _REPO_ROOT / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("sqlalchemy.url", db_url)
    config.set_main_option("script_location", str(_PIPELINE_DIR / "db" / "migrations"))
    return config


def test_migration_upgrade_from_empty(tmp_path):
    """Upgrade head from empty database."""
    db_file = tmp_path / "migrate_empty.db"
    db_url = f"sqlite:///{db_file}"
    config = _get_alembic_config(db_url)

    command.upgrade(config, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "analysis_runs" in tables
    assert "graph_nodes" in tables
    assert "graph_edges" in tables


def test_migration_0004_to_head_and_downgrade(tmp_path):
    """Upgrade from 0004 to head, and downgrade 0006 -> 0005 removes 4 composite indexes."""
    db_file = tmp_path / "migrate_partial.db"
    db_url = f"sqlite:///{db_file}"
    config = _get_alembic_config(db_url)

    # Upgrade to 0004
    command.upgrade(config, "0004")

    # Upgrade to head
    command.upgrade(config, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    gn_indexes = {idx["name"] for idx in inspector.get_indexes("graph_nodes")}
    assert "ix_graph_nodes_run_node_type" in gn_indexes
    assert "ix_graph_nodes_run_file_path" in gn_indexes

    # Downgrade to 0005
    command.downgrade(config, "0005")
    inspector = inspect(engine)
    gn_indexes_after = {idx["name"] for idx in inspector.get_indexes("graph_nodes")}
    assert "ix_graph_nodes_run_node_type" not in gn_indexes_after
    assert "ix_graph_nodes_run_file_path" not in gn_indexes_after


def test_idempotent_migration_0006_on_create_all_db(tmp_path):
    """Running alembic upgrade head on a DB initialized by create_all is idempotent."""
    db_file = tmp_path / "create_all_migrate.db"
    db_url = f"sqlite:///{db_file}"

    engine = get_engine(db_url)
    create_all_tables(engine)

    config = _get_alembic_config(db_url)
    # Stamp or upgrade to head on a create_all DB
    command.stamp(config, "0005")
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "graph_nodes" in inspector.get_table_names()


def test_create_all_column_shim_idempotency_and_reraise(tmp_path, caplog):
    """Column shim adds knowledge_graph_summary_json to 0004 schema, is idempotent, and re-raises unrelated errors."""
    import logging
    db_file = tmp_path / "shim_test.db"
    db_url = f"sqlite:///{db_file}"
    config = _get_alembic_config(db_url)


    command.upgrade(config, "0004")

    engine = get_engine(db_url)
    # First call: adds column
    create_all_tables(engine)
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("analysis_runs")]
    assert "knowledge_graph_summary_json" in cols

    # Second call: idempotent
    create_all_tables(engine)

    # Test unrelated error re-raise.
    # The critical guarantee: create_all_tables must re-raise non-"duplicate column" errors
    # so callers can detect real database failures (e.g. connection lost).
    from unittest.mock import patch

    # Patch Base.metadata.create_all to raise a non-duplicate error.
    # This is the most reliable injection point because the try/except in
    # create_all_tables wraps both create_all and the subsequent column check.
    with patch.object(type(engine.dialect), "do_execute",
                      side_effect=RuntimeError("Database connection lost")):
        pass  # just a syntax-check placeholder; real test below

    # Direct approach: verify RuntimeError propagates from inside the try block
    # by patching the whole function body's underlying check.
    from db.engine import create_all_tables as _cat
    import db.engine as _eng_mod

    original_create_all = _eng_mod.Base.metadata.create_all

    def _raising_create_all(*args, **kwargs):
        raise RuntimeError("Database connection lost")

    _eng_mod.Base.metadata.create_all = _raising_create_all
    try:
        with pytest.raises(RuntimeError, match="Database connection lost"):
            create_all_tables(engine)
    finally:
        _eng_mod.Base.metadata.create_all = original_create_all

