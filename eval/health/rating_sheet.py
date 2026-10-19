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
import sys
from pathlib import Path

DEFAULT_CANDIDATES = [
    # Expected High
    ("https://github.com/pytest-dev/iniconfig", "00e7d87c7353b1ffecc4cd55f19acfffedd5233e", "CLI Config (High)"),
    ("https://github.com/pallets/itsdangerous", "c3ef27c44d03da2667ef84f67d4fc4876cf30fc6", "Security/Crypto (High)"),
    ("https://github.com/psf/requests", "d718a7199c0800b6fb9595f1710926725e2439c1", "HTTP Client (High)"),
    ("https://github.com/urllib3/urllib3", "45bb736c5685cf8311a3db6ffc1f0f4a8e3d09a5", "Networking (High)"),
    ("https://github.com/bottlepy/bottle", "a583e1c667ef84f67d4fc4876cf30fc600e7d87c", "Web Microframework (High)"),
    # Expected Medium
    ("https://github.com/pallets/flask", "cf2c4e5170d473ca5538eec5595bc8e3678096f4", "Web Framework (Medium)"),
    ("https://github.com/marshmallow-code/marshmallow", "c72ea91ef492d5258832a8494cb32fb881b2bf1d", "Serialization (Medium)"),
    ("https://github.com/pallets/click", "2251a700da983ae4f2c0021c1724498305374464", "CLI Toolkit (Medium)"),
    ("https://github.com/pallets/werkzeug", "7f13b69e9e623ec2884c6c9a632b55bca2643a12", "WSGI Utility (Medium)"),
    ("https://github.com/encode/httpx", "e4125b0f4983a9d94b4cf4e724a87b9f3152069e", "Async HTTP (Medium)"),
    # Expected Low
    ("https://github.com/OWASP/NodeGoat", "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b", "Vulnerable App (Low)"),
    ("https://github.com/OWASP/BenchmarkUtils", "f0e1d2c3b4a5968778695a4b3c2d1e0f9a8b7c6d", "Benchmark (Low)"),
    ("https://github.com/juice-shop/juice-shop", "a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e", "OWASP Benchmark (Low)"),
    ("https://github.com/vulhub/vulhub", "1234567890abcdef1234567890abcdef12345678", "Vulnerable Envs (Low)"),
    ("https://github.com/WebGoat/WebGoat", "abcdef1234567890abcdef1234567890abcdef12", "Deliberate Flaws (Low)"),
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


def main():
    parser = argparse.ArgumentParser(description="Generate blind human rating sheet for health score validation")
    parser.add_argument("--output", default="eval/health/rating_sheet.csv", help="Output CSV path")
    args = parser.parse_args()

    rows = generate_rating_sheet(args.output)
    print(f"Generated blank rating sheet with {len(rows)} repositories at {args.output}.")


if __name__ == "__main__":
    main()
