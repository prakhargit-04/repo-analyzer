#!/usr/bin/env python3
"""
Generates an annotation sheet of sampled graph edges for human evaluation.
Stratifies sampling across edge types (calls, imports, inherits, contains)
with all labels empty for blind human review.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from parser_interface import parse_repository
from graph_builder import build_graph


def extract_symbol_info(node_id: str, node_data: dict) -> tuple[str, str]:
    """Returns (file_path, symbol_name) from node id and attribute dictionary."""
    ntype = node_data.get("type", "")
    if ntype == "file":
        return str(node_id), ""
    file_path = node_data.get("file", "")
    name = node_data.get("name", "")
    if not name:
        if "::" in str(node_id):
            name = str(node_id).split("::", 1)[1]
        else:
            name = str(node_id)
    return file_path, name


def generate_annotation_sheet(
    repo_path: str,
    repo_id: str = "local/repo",
    sha: str = "HEAD",
    sample_size: int = 50,
    seed: int = 42,
    output_path: str | None = None,
) -> list[dict[str, str]]:
    """Parse repository, build graph, sample edges stratified by type, and write CSV."""
    random.seed(seed)
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        raise ValueError(f"Repository directory does not exist: {repo_path}")

    parse_results = parse_repository(repo_path)
    g = build_graph(parse_results)

    # Group edges by relation
    by_type: dict[str, list[tuple[Any, Any, dict]]] = defaultdict(list)
    for u, v, data in g.edges(data=True):
        rel = data.get("relation", "unknown")
        by_type[rel].append((u, v, data))

    # Stratified sampling across core relationship types
    target_types = ["calls", "imports", "inherits", "contains"]
    available_types = [t for t in target_types if len(by_type[t]) > 0]
    if not available_types:
        available_types = list(by_type.keys())

    sampled_edges: list[tuple[Any, Any, dict]] = []
    if available_types:
        per_type_quota = max(1, math.floor(sample_size / len(available_types)))
        remaining_pool: list[tuple[Any, Any, dict]] = []

        for t in available_types:
            pool = by_type[t]
            k = min(len(pool), per_type_quota)
            chosen = random.sample(pool, k)
            sampled_edges.extend(chosen)
            remaining_pool.extend([e for e in pool if e not in chosen])

        # If we have not reached sample_size yet, fill from remaining
        needed = sample_size - len(sampled_edges)
        if needed > 0 and remaining_pool:
            sampled_edges.extend(random.sample(remaining_pool, min(needed, len(remaining_pool))))

    # Shuffle sampled edges so edge types are mixed
    random.shuffle(sampled_edges)

    rows: list[dict[str, str]] = []
    for u, v, data in sampled_edges:
        u_data = g.nodes.get(u, {})
        v_data = g.nodes.get(v, {})
        src_file, src_sym = extract_symbol_info(u, u_data)
        tgt_file, tgt_sym = extract_symbol_info(v, v_data)
        edge_type = data.get("relation", "")

        rows.append({
            "repo": repo_id,
            "sha": sha,
            "edge_type": edge_type,
            "source_file": src_file,
            "source_symbol": src_sym,
            "target_file": tgt_file,
            "target_symbol": tgt_sym,
            "label": "",
            "labeled_by": "",
            "reviewed_by_human": "",
        })

    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        fieldnames = [
            "repo", "sha", "edge_type", "source_file", "source_symbol",
            "target_file", "target_symbol", "label", "labeled_by", "reviewed_by_human"
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate stratified graph edge annotation sheet for human review")
    parser.add_argument("--repo-path", required=True, help="Path to repository to analyze")
    parser.add_argument("--repo-id", default="repo", help="Repository identifier")
    parser.add_argument("--sha", default="HEAD", help="Commit SHA")
    parser.add_argument("--sample-size", type=int, default=50, help="Total sample count")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", default="eval/graph/samples/sample.csv", help="Output CSV path")
    args = parser.parse_args()

    rows = generate_annotation_sheet(
        repo_path=args.repo_path,
        repo_id=args.repo_id,
        sha=args.sha,
        sample_size=args.sample_size,
        seed=args.seed,
        output_path=args.output,
    )
    print(f"Generated {len(rows)} sampled edges written to {args.output} (all labels empty).")


if __name__ == "__main__":
    main()
