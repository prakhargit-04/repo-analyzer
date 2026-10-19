#!/usr/bin/env python3
import os
import subprocess
import sys
import tempfile
import shutil

repos = [
    {
        "name": "iniconfig",
        "url": "https://github.com/pytest-dev/iniconfig.git",
        "ref": "v2.0.0",
        "output": os.path.join("docs", "s25_evidence", "a2_explain_score_iniconfig.txt")
    },
    {
        "name": "itsdangerous",
        "url": "https://github.com/pallets/itsdangerous.git",
        "ref": "2.1.2",
        "output": os.path.join("docs", "s25_evidence", "a2_explain_score_itsdangerous.txt")
    }
]

for r in repos:
    print(f"Cloning {r['name']} at {r['ref']}...")
    tmp = tempfile.mkdtemp(prefix=f"eval_repo_{r['name']}_")
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--branch", r["ref"], r["url"], tmp], check=True, capture_output=True, text=True)
        # get exact commit sha
        sha_proc = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        sha = sha_proc.stdout.strip()
        print(f"Cloned {r['name']} at commit {sha}. Running explain_score...")
        res = subprocess.run([sys.executable, "scripts/explain_score.py", tmp], capture_output=True, text=True)
        out_content = f"Repository: {r['url']}\nPinned Ref: {r['ref']}\nCommit SHA: {sha}\n\n" + res.stdout + ("\nSTDERR:\n" + res.stderr if res.stderr else "")
        with open(r["output"], "w", encoding="utf-8") as f:
            f.write(out_content)
        print(f"Saved {r['output']}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
