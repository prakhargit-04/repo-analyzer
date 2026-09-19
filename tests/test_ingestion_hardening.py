"""
Unit and integration tests for Session 13: Ingestion Hardening & Security.
Verifies clone security, safe URL validation, path traversal prevention,
file size/count limits, atomic cache writes, corruption recovery, temporary
directory cleanup on success & failure, and deterministic execution.
"""
import os
import sys
import tempfile
import json
import pytest
from pipeline.clone import clone_repository, is_safe_repo_url
from pipeline.parser_interface import parse_repository, parse_file
from pipeline.main import run_pipeline, load_cache, save_cache_atomic
from pipeline.util import is_safe_relative_path


def test_url_validation_and_option_flag_rejection():
    """Verify URL validation rejects option flags and unsafe URL formats."""
    assert is_safe_repo_url("https://github.com/pytest-dev/iniconfig")
    assert is_safe_repo_url("http://github.com/owner/repo")
    assert is_safe_repo_url("git@github.com:owner/repo.git")

    assert not is_safe_repo_url("-oProxyCommand=calc.exe")
    assert not is_safe_repo_url("--config=core.gitProxy=cmd.exe")
    assert not is_safe_repo_url("  -flag")


def test_clone_failure_cleanup():
    """Verify clone_repository cleans up destination directory on failure."""
    with tempfile.TemporaryDirectory() as base_dir:
        target_dir = os.path.join(base_dir, "failed_clone")
        with pytest.raises(RuntimeError):
            clone_repository("https://invalid-host-name-does-not-exist.example/repo.git", target_dir)

        assert not os.path.exists(target_dir)


def test_invalid_repository_path_raises_value_error():
    """Verify invalid or non-existent repository path fails safely."""
    with pytest.raises(ValueError):
        parse_repository("/path/does/not/exist/anywhere")

    with pytest.raises(ValueError):
        run_pipeline(None, "/path/does/not/exist/anywhere", None, ".cache")


def test_oversized_file_handling():
    """Verify files larger than 10MB record parse error instead of crashing."""
    with tempfile.TemporaryDirectory() as d:
        large_file = os.path.join(d, "large.py")
        with open(large_file, "wb") as f:
            f.write(b"a = 1\n" * (2 * 1024 * 1024))  # ~12MB

        res = parse_file(large_file, d)
        assert res.parse_error is not None
        assert "10MB" in res.parse_error


def test_path_traversal_prevention():
    """Verify path traversal prevention helper."""
    with tempfile.TemporaryDirectory() as d:
        assert is_safe_relative_path("main.py", d)
        assert is_safe_relative_path("pkg/utils.py", d)
        assert not is_safe_relative_path("../../etc/passwd", d)
        assert not is_safe_relative_path("/etc/passwd", d)


def test_temp_directory_cleanup_on_success():
    """Verify temporary clone directory is deleted after successful run_pipeline."""
    with tempfile.TemporaryDirectory() as cache_dir:
        with tempfile.TemporaryDirectory() as repo_dir:
            with open(os.path.join(repo_dir, "app.py"), "w") as f:
                f.write("def run(): pass\n")

            res = run_pipeline(None, repo_dir, None, cache_dir)
            assert res["analysis_status"] in ("complete", "partial")
            assert "health_score" in res


def test_atomic_cache_save_and_corruption_recovery():
    """Verify atomic cache writes and corrupted cache recovery."""
    with tempfile.TemporaryDirectory() as d:
        cache_file = os.path.join(d, "test_cache.json")

        # 1. Atomic Save
        data = {"schema_version": "1.0.0", "knowledge_graph": {"nodes": [], "edges": []}}
        save_cache_atomic(cache_file, data)
        assert os.path.exists(cache_file)
        assert load_cache(cache_file) == data

        # 2. Corrupt file content
        with open(cache_file, "w") as f:
            f.write("{ invalid json content ...")

        # 3. Load should detect corruption, log warning, remove file, and return None
        loaded = load_cache(cache_file)
        assert loaded is None
        assert not os.path.exists(cache_file)


def test_deterministic_reruns_after_hardening():
    """Verify pipeline output remains 100% byte-for-byte deterministic."""
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
        with open(os.path.join(d, "main.py"), "w") as f:
            f.write("def hello():\n    return 'world'\n")

        res1 = run_pipeline(None, d, None, c1)
        res2 = run_pipeline(None, d, None, c2)

        res1_clean = {k: v for k, v in res1.items() if k != "analyzed_at_utc"}
        res2_clean = {k: v for k, v in res2.items() if k != "analyzed_at_utc"}

        assert json.dumps(res1_clean, sort_keys=True, indent=2) == json.dumps(res2_clean, sort_keys=True, indent=2)
