#!/usr/bin/env python3
"""
Independent Python AST Import Oracle for Cross-Checking Graph Builder Imports.

Extracts imports using Python standard library `ast` without tree-sitter dependencies
and computes agreement rate, false positives, and false negatives in graph_builder.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Dict, Set, Tuple, Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
for p in [str(REPO_ROOT), str(PIPELINE_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from parser_interface import parse_repository
from graph_builder import build_graph


def normalize_relpath(path: str, root: str) -> str:
    """Normalize file paths with forward slashes relative to root."""
    rel = os.path.relpath(path, root)
    return rel.replace("\\", "/").lstrip("./")


def extract_ast_imports(repo_path: str) -> set[tuple[str, str, str | None]]:
    """
    Extract imports from Python files using Python's native ast module.
    Returns set of tuples: (source_relpath, imported_symbol, alias_or_none).
    """
    oracle_imports: set[tuple[str, str, str | None]] = set()

    for dirpath, dirnames, filenames in os.walk(repo_path):
        # Skip dot directories, virtual environments, build artifacts
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("venv", "env", "node_modules", "dist", "build", "__pycache__")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full_path = os.path.join(dirpath, fn)
            rel_path = normalize_relpath(full_path, repo_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source, filename=rel_path)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        oracle_imports.add((rel_path, alias.name, alias.asname))
                elif isinstance(node, ast.ImportFrom):
                    level = getattr(node, "level", 0)
                    module = getattr(node, "module", None) or ""
                    prefix = ("." * level) + module if level > 0 else module
                    for alias in node.names:
                        if prefix:
                            imported = f"{prefix}.{alias.name}" if alias.name != "*" else f"{prefix}.*"
                        else:
                            imported = alias.name
                        oracle_imports.add((rel_path, imported, alias.asname))

    return oracle_imports


def extract_builder_imports(repo_path: str) -> set[tuple[str, str, str | None]]:
    """
    Extract imports from graph_builder pipeline.
    Returns set of tuples: (source_relpath, imported_symbol, alias_or_none).
    """
    parse_results = parse_repository(repo_path)
    g = build_graph(parse_results)

    builder_imports: set[tuple[str, str, str | None]] = set()
    for u, v, data in g.edges(data=True):
        if data.get("relation") == "imports":
            src_file = g.nodes[u].get("file") or (u if g.nodes[u].get("type") == "file" else "")
            imported = data.get("imported")
            if not imported:
                v_name = g.nodes[v].get("name")
                if not v_name and str(v).startswith("import::"):
                    v_name = str(v).split("::", 1)[1]
                imported = v_name or str(v)
            alias = data.get("alias")
            builder_imports.add((src_file, imported, alias))

    return builder_imports


def evaluate_imports(repo_path: str) -> dict[str, Any]:
    """Compare AST oracle imports against builder imports."""
    oracle_set = extract_ast_imports(repo_path)
    builder_set = extract_builder_imports(repo_path)

    tp = oracle_set & builder_set
    fp = builder_set - oracle_set
    fn = oracle_set - builder_set

    total_union = len(oracle_set | builder_set)
    jaccard_agreement = len(tp) / total_union if total_union > 0 else 1.0
    dice_agreement = (2 * len(tp)) / (len(oracle_set) + len(builder_set)) if (len(oracle_set) + len(builder_set)) > 0 else 1.0

    return {
        "repo_path": repo_path,
        "oracle_import_count": len(oracle_set),
        "builder_import_count": len(builder_set),
        "true_positives": len(tp),
        "false_positives_in_builder": len(fp),
        "false_negatives_in_builder": len(fn),
        "jaccard_agreement_rate": round(jaccard_agreement, 4),
        "dice_agreement_rate": round(dice_agreement, 4),
        "sample_fp": [list(x) for x in list(fp)[:5]],
        "sample_fn": [list(x) for x in list(fn)[:5]],
    }


def main():
    parser = argparse.ArgumentParser(description="Cross-check graph_builder imports against independent Python AST oracle")
    parser.add_argument("--repo-path", required=True, help="Path to repository to cross-check")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    results = evaluate_imports(args.repo_path)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"=== Import Oracle Cross-Check: {args.repo_path} ===")
        print(f"Oracle AST Imports Count:     {results['oracle_import_count']}")
        print(f"Builder Graph Imports Count:  {results['builder_import_count']}")
        print(f"True Positive Matches:        {results['true_positives']}")
        print(f"False Positives in Builder:   {results['false_positives_in_builder']}")
        print(f"False Negatives in Builder:   {results['false_negatives_in_builder']}")
        print(f"Jaccard Agreement Rate:       {results['jaccard_agreement_rate'] * 100:.2f}%")
        print(f"Dice Agreement Rate:          {results['dice_agreement_rate'] * 100:.2f}%")
        if results['sample_fp']:
            print(f"Sample False Positives: {results['sample_fp']}")
        if results['sample_fn']:
            print(f"Sample False Negatives: {results['sample_fn']}")


if __name__ == "__main__":
    main()
