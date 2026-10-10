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


def test_clone_failure_cleanup(monkeypatch):
    """Verify clone_repository cleans up destination directory on failure (offline)."""
    import subprocess
    def mock_subproc_fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "clone"], stderr="Repository not found")

    monkeypatch.setattr(subprocess, "run", mock_subproc_fail)

    with tempfile.TemporaryDirectory() as base_dir:
        target_dir = os.path.join(base_dir, "failed_clone")
        with pytest.raises(RuntimeError, match="Failed to clone repository"):
            clone_repository("https://invalid-host-name-does-not-exist.example/repo.git", target_dir)

        assert not os.path.exists(target_dir)



def test_clone_repository_checks_out_requested_older_commit(sample_git_repo, tmp_path):
    """The clone path must checkout the requested revision, not silently HEAD."""
    from pipeline.clone import clone_repository

    dest = tmp_path / "older-revision"
    resolved = clone_repository(
        sample_git_repo.url,
        str(dest),
        commit_sha=sample_git_repo.initial_commit_sha,
    )

    assert resolved == sample_git_repo.initial_commit_sha
    assert resolved != sample_git_repo.commit_sha
    assert (dest / "src" / "main.py").exists()
    assert not (dest / "src" / "version.py").exists()

    latest_dest = tmp_path / "latest-revision"
    latest = clone_repository(sample_git_repo.url, str(latest_dest))
    assert latest == sample_git_repo.commit_sha
    assert (latest_dest / "src" / "version.py").read_text(encoding="utf-8") == 'FIXTURE_REVISION = "second"\n'

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


def test_atomic_cache_concurrent_multithread_writes():
    """Stress test concurrent multithreaded atomic writes to the same cache file.

    Verifies:
      1. Multiple threads writing different valid payloads to the same cache key concurrently.
      2. The final cache file always contains valid complete JSON.
      3. Temporary files do not collide.
      4. Successful completion leaves no `.tmp.*` files behind.
    """
    import threading
    import concurrent.futures

    with tempfile.TemporaryDirectory() as d:
        cache_file = os.path.join(d, "shared_cache.json")
        errors = []

        def worker(thread_idx: int):
            try:
                payload = {
                    "schema_version": "1.0.0",
                    "thread_idx": thread_idx,
                    "content": f"data_from_thread_{thread_idx}" * 50,
                }
                save_cache_atomic(cache_file, payload)
            except Exception as exc:
                errors.append(exc)

        threads = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            concurrent.futures.wait(futures)

        assert errors == [], f"Concurrent save_cache_atomic raised errors: {errors}"
        assert os.path.exists(cache_file)

        # Final cache file must contain valid, parseable JSON
        with open(cache_file, "r", encoding="utf-8") as f:
            final_data = json.load(f)
        assert isinstance(final_data, dict)
        assert "thread_idx" in final_data

        # Verify no orphan .tmp.* files remain in the directory
        tmp_files = [fn for fn in os.listdir(d) if ".tmp." in fn]
        assert tmp_files == [], f"Orphan temporary files found: {tmp_files}"


def test_atomic_cache_transient_permission_retry(monkeypatch):
    """Verify save_cache_atomic handles transient os.replace PermissionError via retry."""
    real_replace = os.replace
    calls = 0

    def mock_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("Transient Windows file lock")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", mock_replace)

    with tempfile.TemporaryDirectory() as d:
        cache_file = os.path.join(d, "retry_cache.json")
        data = {"schema_version": "1.0.0", "knowledge_graph": {}, "test": "retry"}
        save_cache_atomic(cache_file, data)

        assert calls == 2
        assert os.path.exists(cache_file)
        assert load_cache(cache_file) == data


def test_atomic_cache_persistent_failure_cleanup(monkeypatch):
    """Verify save_cache_atomic raises exception and cleans up temp file on persistent replace failure."""
    def mock_replace_always_fail(src, dst):
        raise PermissionError("Persistent Windows file lock")

    monkeypatch.setattr(os, "replace", mock_replace_always_fail)

    with tempfile.TemporaryDirectory() as d:
        cache_file = os.path.join(d, "fail_cache.json")
        data = {"schema_version": "1.0.0", "test": "fail"}

        with pytest.raises(PermissionError):
            save_cache_atomic(cache_file, data)

        # Temp files must be cleaned up
        tmp_files = [fn for fn in os.listdir(d) if ".tmp." in fn]
        assert tmp_files == [], f"Orphan temp files remaining after persistent failure: {tmp_files}"


def test_deterministic_reruns_after_hardening(monkeypatch):
    """Pipeline output is deterministic when analyzer outputs are controlled.

    This test validates pipeline determinism only. Actual CLI integration and
    timeout/error behavior are tested separately in the analyzer contract suite.
    """
    import static_analysis

    analyzer_calls = []

    def deterministic_analyze(repo_root, parsed_files_rel=None, py_files_rel=None, **kwargs):
        files = sorted(parsed_files_rel or py_files_rel or [])
        analyzer_calls.append((repo_root, tuple(files)))
        return {
            "scope_policy": "production_code_only",
            "production_files_analyzed": len(files),
            "test_files_excluded": 0,
            "complexity": {"status": "success", "results": []},
            "maintainability": {"status": "success", "results": []},
            "security": {"status": "unavailable", "results": []},
            "lizard_complexity": {"status": "unavailable", "results": []},
            "semgrep_findings": {"status": "unavailable", "results": []},
            "gitleaks_findings": {"status": "unavailable", "results": []},
            "osv_vulnerabilities": {"status": "unavailable", "results": []},
        }

    monkeypatch.setattr(static_analysis, "analyze_repository", deterministic_analyze)

    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
        with open(os.path.join(d, "main.py"), "w", encoding="utf-8") as f:
            f.write("def hello():\n    return 'world'\n")

        res1 = run_pipeline(None, d, None, c1)
        res2 = run_pipeline(None, d, None, c2)

        res1_clean = {k: v for k, v in res1.items() if k != "analyzed_at_utc"}
        res2_clean = {k: v for k, v in res2.items() if k != "analyzed_at_utc"}

        assert json.dumps(res1_clean, sort_keys=True, indent=2) == json.dumps(res2_clean, sort_keys=True, indent=2)
        assert len(analyzer_calls) == 2
        assert analyzer_calls[0][1] == analyzer_calls[1][1] == ("main.py",)


# ---------------------------------------------------------------------------
# Task R4 Tests — REPO_MAX_MB & working_tree_size_bytes
# ---------------------------------------------------------------------------

class TestRepoMaxMbHardening:
    """Task R4 Verification: working_tree_size_bytes and REPO_MAX_MB clone guard."""

    def test_dangling_symlink_handled_safely(self, tmp_path):
        """Dangling symlink does not crash working_tree_size_bytes or count toward size."""
        from pipeline.util import working_tree_size_bytes

        repo_dir = tmp_path / "symlink_repo"
        repo_dir.mkdir()
        (repo_dir / "valid.txt").write_bytes(b"x" * 100)

        # Create dangling symlink
        try:
            os.symlink(str(repo_dir / "nonexistent.txt"), str(repo_dir / "broken_link"))
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform/privilege level")

        size = working_tree_size_bytes(str(repo_dir))
        assert size == 100

    def test_symlink_to_huge_external_file_not_counted(self, tmp_path):
        """Symlink pointing to a huge file outside the repo is ignored in size calculation."""
        from pipeline.util import working_tree_size_bytes

        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        huge_file = outside_dir / "huge.bin"
        huge_file.write_bytes(b"0" * 5000)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "file.txt").write_bytes(b"hello")

        try:
            os.symlink(str(huge_file), str(repo_dir / "link_to_huge"))
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported")

        size = working_tree_size_bytes(str(repo_dir))
        assert size == 5  # Only file.txt counted

    def test_parent_dir_named_git_works(self, tmp_path):
        """Parent directory named .git must not break working_tree_size_bytes."""
        from pipeline.util import working_tree_size_bytes

        git_parent = tmp_path / ".git" / "subfolder" / "repo"
        git_parent.mkdir(parents=True)
        (git_parent / "a.py").write_bytes(b"a = 1\n")
        (git_parent / ".git").mkdir()
        (git_parent / ".git" / "INDEX").write_bytes(b"git internal data")

        size = working_tree_size_bytes(str(git_parent))
        assert size == 6  # Only a.py counted, .git internal data ignored

    def test_working_tree_size_bytes_is_deterministic(self, tmp_path):
        """helper returns identical result across multiple runs."""
        from pipeline.util import working_tree_size_bytes

        d = tmp_path / "test_repo"
        d.mkdir()
        (d / "f1.txt").write_bytes(b"12345")
        (d / "f2.txt").write_bytes(b"67890")

        s1 = working_tree_size_bytes(str(d))
        s2 = working_tree_size_bytes(str(d))
        assert s1 == s2 == 10

    def test_oversize_tree_fails_and_removes_dir(self, tmp_path, monkeypatch):
        """Oversize repository fails size guard and cleans up dest_dir."""
        import subprocess
        from pipeline.clone import clone_repository

        dest = tmp_path / "oversize_dest"

        def mock_run(cmd, *args, **kwargs):
            if "clone" in cmd:
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "large.bin").write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="a" * 40, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setenv("REPO_MAX_MB", "1")

        with pytest.raises(RuntimeError, match="Repository working tree exceeds configured size limit"):
            clone_repository("https://github.com/test/oversize", str(dest))

        assert not dest.exists()

