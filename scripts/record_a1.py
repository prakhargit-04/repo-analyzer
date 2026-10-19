import os
import subprocess
import sys
import platform
import json
import urllib.request

output_lines = []

def run_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (res.stdout + res.stderr).strip()
    except Exception as e:
        return f"ERROR: {e}"

output_lines.append("=== A1 FORENSICS ===")
output_lines.append(f"Date/Time: 2026-10-19T15:35:00")

# Git status & latest commit
output_lines.append("\n--- GIT STATUS ---")
output_lines.append(run_cmd("git status"))
output_lines.append("\n--- LATEST COMMIT ---")
output_lines.append(run_cmd("git log -1 --stat"))

# OS, Python, Node
output_lines.append("\n--- SYSTEM ENVIRONMENT ---")
output_lines.append(f"OS: {platform.platform()} ({sys.platform})")
output_lines.append(f"Python: {sys.version.splitlines()[0]}")
output_lines.append(f"Python Executable: {sys.executable}")
output_lines.append(f"Node: {run_cmd('node --version')}")
output_lines.append(f"NPM: {run_cmd('npm --version')}")

# Analyzers
output_lines.append("\n--- ANALYZERS AVAILABILITY ---")
analyzers = ["semgrep", "gitleaks", "bandit", "radon", "lizard"]
for tool in analyzers:
    ver = run_cmd(f"{tool} --version")
    output_lines.append(f"{tool}: {ver}")

# api.osv.dev reachability
output_lines.append("\n--- OSV REACHABILITY ---")
try:
    payload = json.dumps({"package": {"name": "jinja2", "ecosystem": "PyPI"}, "version": "2.4.1"}).encode("utf-8")
    req = urllib.request.Request("https://api.osv.dev/v1/query", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read()
        output_lines.append(f"api.osv.dev status: {resp.status}, response bytes: {len(body)}")
except Exception as e:
    output_lines.append(f"api.osv.dev reachability check FAILED: {e}")

out_path = os.path.join("docs", "s25_evidence", "a1_forensics.txt")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines) + "\n")

print(f"Saved to {out_path}")
for line in output_lines:
    print(line)
