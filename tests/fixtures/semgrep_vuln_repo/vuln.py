"""Fixture with intentional security issues for Semgrep testing."""
import subprocess
import os

def run_cmd(user_input: str) -> str:
    # CWE-78: OS Command Injection -- intentionally vulnerable fixture
    result = subprocess.run(user_input, shell=True, capture_output=True, text=True)
    return result.stdout

def read_file(path: str) -> str:
    # CWE-22: Path traversal -- intentionally vulnerable fixture
    with open(path, "r") as f:
        return f.read()
