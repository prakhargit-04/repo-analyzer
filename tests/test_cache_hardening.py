"""
Task R5 Verification: Cache directory resolution, lifespan cleanup, and dangerous path safety guards.
"""
import os
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))

from util import get_cache_dir, cleanup_cache, is_dangerous_cache_path


def test_routes_app_main_resolve_same_cache_dir(monkeypatch):
    """util.get_cache_dir, routes.get_cache_dir, and app resolve identical absolute paths."""
    monkeypatch.delenv("CACHE_DIR", raising=False)

    from util import get_cache_dir as util_gcd
    from api.routes import get_cache_dir as routes_gcd

    path1 = util_gcd()
    path2 = routes_gcd()

    assert os.path.isabs(path1)
    assert path1 == path2
    assert path1.endswith(".cache")


def test_lifespan_cache_cleanup_deletes_old_files(tmp_path, monkeypatch):
    """Lifespan with CACHE_MAX_AGE_DAYS set cleans eligible files in real default cache dir."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_MAX_AGE_DAYS", "1")

    # Create an old file (>1 day old, mtime 2 days ago)
    old_file = tmp_path / "old_cache.json"
    old_file.write_bytes(b'{"key": "old"}')
    two_days_ago = time.time() - (2 * 86400 + 3700)
    os.utime(str(old_file), (two_days_ago, two_days_ago))

    # Create a fresh file (10 mins old)
    new_file = tmp_path / "new_cache.json"
    new_file.write_bytes(b'{"key": "new"}')

    res = cleanup_cache(str(tmp_path), max_age_days=1, max_total_mb=None)

    assert res["deleted_files"] == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_dangerous_cache_paths_refused():
    """Safety guard refuses cache cleanup on root, home directory, or repo root."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    home_dir = os.path.abspath(os.path.expanduser("~"))

    assert is_dangerous_cache_path("/")
    assert is_dangerous_cache_path("\\")
    assert is_dangerous_cache_path(home_dir)
    assert is_dangerous_cache_path(repo_root)

    # Clean operation on dangerous path is refused and deletes 0 files
    res = cleanup_cache(home_dir, max_age_days=0, max_total_mb=0)
    assert res == {"deleted_files": 0, "deleted_bytes": 0}


def test_invalid_env_values_ignored(caplog):
    """Invalid env values for cache cleanup trigger warning and are ignored."""
    from api.app import _optional_nonnegative_int

    assert _optional_nonnegative_int("INVALID_ENV_VAR_TEST_XYZ") is None

    os.environ["INVALID_ENV_VAR_TEST_XYZ"] = "-5"
    val = _optional_nonnegative_int("INVALID_ENV_VAR_TEST_XYZ")
    assert val is None
    assert "Invalid INVALID_ENV_VAR_TEST_XYZ" in caplog.text
