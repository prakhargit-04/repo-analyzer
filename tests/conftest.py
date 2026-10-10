"""
Puts pipeline/ on sys.path so tests import the modules the same way
main.py does (flat imports, no package prefix) rather than duplicating
import logic here.
"""
import os
import sys
import subprocess
import pytest

PIPELINE_DIR = os.path.join(os.path.dirname(__file__), "..", "pipeline")
sys.path.insert(0, os.path.abspath(PIPELINE_DIR))


class LocalGitRepo:
    def __init__(self, path: str, commit_sha: str, url: str, initial_commit_sha: str):
        self.path = path
        self.commit_sha = commit_sha
        self.initial_commit_sha = initial_commit_sha
        self.url = url


@pytest.fixture
def sample_git_repo(tmp_path_factory):
    """Creates a small, deterministic local Git repository for offline integration testing."""
    repo_dir = tmp_path_factory.mktemp("sample_git_repo")

    # Initialize Git repository
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)

    # Create Python source files for parser, graph, and chunker assertions
    pkg_dir = repo_dir / "src"
    os.makedirs(pkg_dir, exist_ok=True)

    main_py = pkg_dir / "main.py"
    main_py.write_text(
        "def main():\n"
        "    print('Hello World')\n"
        "\n"
        "class App:\n"
        "    def run(self):\n"
        "        main()\n",
        encoding="utf-8",
    )

    utils_py = pkg_dir / "utils.py"
    utils_py.write_text(
        "def helper(x: int) -> int:\n"
        "    return x + 1\n",
        encoding="utf-8",
    )

    # Fixed timestamps make commit IDs reproducible across fixture instances.
    base_env = os.environ.copy()
    base_env.update({
        "GIT_AUTHOR_DATE": "2020-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+0000",
    })
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True, env=base_env)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True, env=base_env)
    initial_sha_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True,
        capture_output=True, text=True,
    )
    initial_commit_sha = initial_sha_proc.stdout.strip()

    # Add a second revision so tests can prove that checkout of an older SHA
    # differs from checkout of HEAD (a one-commit fixture cannot catch this).
    version_file = pkg_dir / "version.py"
    version_file.write_text('FIXTURE_REVISION = "second"\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True, env=base_env)
    second_env = base_env.copy()
    second_env.update({
        "GIT_AUTHOR_DATE": "2020-01-02T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2020-01-02T00:00:00+0000",
    })
    subprocess.run(["git", "commit", "-m", "Add fixture version marker"], cwd=repo_dir, check=True, capture_output=True, env=second_env)

    sha_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True)
    commit_sha = sha_proc.stdout.strip()
    file_url = repo_dir.as_uri()

    return LocalGitRepo(
        path=str(repo_dir), commit_sha=commit_sha, url=file_url,
        initial_commit_sha=initial_commit_sha,
    )
