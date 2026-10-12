"""Migration 0008 compatibility tests for config fingerprints and force refresh."""
from __future__ import annotations
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "pipeline"
for item in (str(ROOT), str(PIPELINE)):
    if item not in sys.path:
        sys.path.insert(0, item)
from db.engine import create_all_tables, get_engine


def _config(db_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(PIPELINE / "db" / "migrations"))
    return cfg


def _assert_columns(engine, expected: bool):
    insp = inspect(engine)
    runs = {c["name"] for c in insp.get_columns("analysis_runs")}
    jobs = {c["name"] for c in insp.get_columns("analysis_jobs")}
    assert ("config_fingerprint" in runs) is expected
    assert ("force_refresh" in jobs) is expected


def test_upgrade_0008_from_empty_and_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    _assert_columns(engine, True)
    command.downgrade(cfg, "0007")
    _assert_columns(engine, False)


def test_upgrade_0008_from_0004_and_0006(tmp_path):
    for base in ("0004", "0006"):
        url = f"sqlite:///{tmp_path / (base + '.db')}"
        cfg = _config(url)
        command.upgrade(cfg, base)
        command.upgrade(cfg, "head")
        _assert_columns(create_engine(url), True)


def test_create_all_database_then_stamp_and_upgrade_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path / 'create-all.db'}"
    engine = get_engine(url)
    create_all_tables(engine)
    _assert_columns(engine, True)
    cfg = _config(url)
    # create_all produces the current schema but no alembic_version; stamp current parent
    # before applying the additive migration chain to avoid replaying table-creation revisions.
    command.stamp(cfg, "0007")
    command.upgrade(cfg, "head")
    create_all_tables(engine)
    _assert_columns(engine, True)


def test_create_all_shim_adds_0008_columns_to_preexisting_0007_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'old-create-all.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "0007")
    engine = get_engine(url)
    create_all_tables(engine)
    _assert_columns(engine, True)
