#!/usr/bin/env python3
"""
Blind Human Rating Sheet Generator for Repository Health Validation.

Generates a blank evaluation sheet for software engineers to rate repositories (1-5)
blind to the algorithmic health score.
"""
from __future__ import annotations

import argparse
import csv
import os

DEFAULT_CANDIDATES = [
    ("https://github.com/pytest-dev/iniconfig", "93f5930e668c0d1ddf4597e38dd0dea4e2665e7a", "CLI Configuration Parsing"),
    ("https://github.com/pallets/itsdangerous", "096c8d42545d3b68ea21a4f890fb2b2d8979c0bd", "Cryptographic Data Signing"),
    ("https://github.com/psf/requests", "0e322af87745eff34caffe4df68456ebc20d9068", "HTTP Client Library"),
    ("https://github.com/urllib3/urllib3", "27e2a5c5a7ab6a517252cc8dcef3ffa6ffb8f61a", "HTTP Networking & Connection Pooling"),
    ("https://github.com/bottlepy/bottle", "ab49e0c22491f8acfcb02e4a7b8c648843268233", "Web Microframework"),
    ("https://github.com/pallets/flask", "c12a5d874c5a014495eb2db8a73f40037bc813ac", "Web Application Framework"),
    ("https://github.com/marshmallow-code/marshmallow", "b9646e326c511c11fc07aef4aa0004c14a5d454c", "Object Serialization & Validation"),
    ("https://github.com/pallets/click", "874ca2bc1c30d93a4ac6e36a15ed685eafe89097", "Command Line Interface Toolkit"),
    ("https://github.com/pallets/werkzeug", "f9995e967979eb694d6b31536cc65314fd7e9c8c", "WSGI Web Application Utility"),
    ("https://github.com/encode/httpx", "326b9431c761e1ef1e00b9f760d1f654c8db48c6", "Async HTTP Client"),
    ("https://github.com/OWASP/NodeGoat", "c5cb68a7084e4ae7dcc60e6a98768720a81841e8", "Vulnerable Node.js Application"),
    ("https://github.com/OWASP-Benchmark/BenchmarkJava", "bc5ffeb09fb18ab039806d84ca1f718c2e332c54", "Static Analysis Vulnerability Benchmark"),
    ("https://github.com/juice-shop/juice-shop", "39b46860612990ae18d499a20472172839fe8c77", "Vulnerable Web Application"),
    ("https://github.com/vulhub/vulhub", "9b90d4276f84feed6333286afeb7e1250379a1da", "Vulnerability Environment Recipes"),
    ("https://github.com/WebGoat/WebGoat", "5357a65e054976cd7d79b81ef3906ded050ed921", "Vulnerable Java Training Application"),
]


def generate_rating_sheet(output_csv: str = "eval/health/rating_sheet.csv") -> list[dict[str, str]]:
    """Outputs blank CSV sheet for human expert rating."""
    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    rows = []
    for url, sha, domain in DEFAULT_CANDIDATES:
        rows.append({
            "repo_url": url,
            "commit_sha": sha,
            "domain": domain,
            "human_rating_1_to_5": "",
            "notes": "",
            "evaluator_id": "",
        })

    fieldnames = ["repo_url", "commit_sha", "domain", "human_rating_1_to_5", "notes", "evaluator_id"]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return rows


def export_algorithmic_scores(
    output_csv: str = "eval/health/algorithmic_scores.csv",
    scores_map: dict[tuple[str, str], float] | None = None,
) -> str:
    """
    Outputs a separate CSV with algorithmic health scores.
    Keeps algorithmic scores isolated from the reviewer-facing sheet to preserve blind protocol.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["repo_url", "commit_sha", "algorithmic_score"])
        if scores_map:
            for (url, sha), score in sorted(scores_map.items()):
                writer.writerow([url, sha, f"{float(score):.2f}"])
        else:
            for url, sha, _ in DEFAULT_CANDIDATES:
                writer.writerow([url, sha, ""])
    return output_csv


def main():
    parser = argparse.ArgumentParser(description="Generate blind human rating sheet or separate score export for health score validation")
    parser.add_argument("--output", default="eval/health/rating_sheet.csv", help="Output rating sheet CSV path")
    parser.add_argument("--export-scores", default=None, help="Output path to export separate algorithmic scores CSV")
    args = parser.parse_args()

    if args.export_scores:
        out = export_algorithmic_scores(args.export_scores)
        print(f"Exported algorithmic scores template to {out}.")
    else:
        rows = generate_rating_sheet(args.output)
        print(f"Generated blank blind rating sheet with {len(rows)} repositories at {args.output}.")


if __name__ == "__main__":
    main()

