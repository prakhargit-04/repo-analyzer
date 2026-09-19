"""
Tier 1 pipeline orchestrator (Python-only MVP).

Stages: clone -> parse -> static-analyze -> graph -> health-score -> cache.
Every stage's output is provenance-tagged; nothing here is LLM-guessed.
This is deliberately the *entire* Tier 1 deliverable -- get this rock solid
on real repos before adding Java/JS support or any Tier 2/3 feature.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import shutil
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from clone import clone_repository
from parse_python import parse_repository
from static_analysis import analyze_repository
from graph_builder import build_graph, graph_summary
from health_score import compute_health_score
from util import resolve_snapshot_id, try_git_head_sha, build_cache_key, CACHE_SCHEMA_VERSION, ANALYZER_VERSION


def run_pipeline(repo_url: str | None, local_path: str | None, commit_sha: str | None, cache_dir: str) -> dict:
    cleanup_dir = None
    is_fresh_clone = False
    if local_path:
        repo_root = local_path
        # NOT trusted as a cache key on its own: a local checkout can have
        # uncommitted changes that HEAD does not reflect. resolve_snapshot_id
        # falls back to content-hashing precisely because of this.
        git_sha = try_git_head_sha(local_path)
        resolved_sha = git_sha or "not-a-git-repo"
    else:
        cleanup_dir = tempfile.mkdtemp(prefix="gha_repo_")
        repo_root = os.path.join(cleanup_dir, "repo")
        resolved_sha = clone_repository(repo_url, repo_root, commit_sha)
        is_fresh_clone = True  # safe to trust the SHA alone: nothing can have modified it since clone

    snapshot_id = resolve_snapshot_id(repo_root, is_fresh_clone, resolved_sha)
    # snapshot_id alone says nothing about whether THIS codebase's own
    # behavior changed since a cached result was written -- versioned_key
    # folds in schema/analyzer version so old cache entries can't be served
    # as if they reflect a since-fixed bug.
    versioned_key = build_cache_key(snapshot_id)
    cache_key = f"{os.path.basename(os.path.normpath(local_path or repo_url))}@{versioned_key}"
    cache_path = os.path.join(cache_dir, f"{cache_key.replace('/', '_')}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as fh:
            print(f"[cache hit] {cache_path}", file=sys.stderr)
            return json.load(fh)

    try:
        parse_results = parse_repository(repo_root)
        py_files_rel = [r.file for r in parse_results if not r.parse_error]

        analysis = analyze_repository(repo_root, py_files_rel)
        g = build_graph(parse_results)
        summary = graph_summary(g)
        graph_data = {
    "nodes": [
        {
            "id": node_id,
            **attributes
        }
        for node_id, attributes in g.nodes(data=True)
    ],
    "edges": [
        {
            "source": source,
            "target": target,
            **attributes
        }
        for source, target, attributes in g.edges(data=True)
    ]
}
        health = compute_health_score(analysis)

        result = {
            "repository": repo_url or local_path,
            "commit_sha": resolved_sha,
            "cache_snapshot_id": snapshot_id,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "analyzer_version": ANALYZER_VERSION,
            "cache_key_basis": "git_sha (fresh clone, trusted)" if is_fresh_clone
                               else "content_hash (local path -- git HEAD alone is not "
                                    "trusted because working tree may have uncommitted changes)",
            "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
            "files_analyzed": len(py_files_rel),
            "parse_errors": [{"file": r.file, "error": r.parse_error} for r in parse_results if r.parse_error],
            "static_analysis": analysis,
            "knowledge_graph_summary": summary,
            "knowledge_graph": graph_data,
            "health_score": health,
        }
    finally:
        if cleanup_dir:
            shutil.rmtree(cleanup_dir, ignore_errors=True)

    os.makedirs(cache_dir, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(result, fh, indent=2)

    return result


def main():
    ap = argparse.ArgumentParser(description="GitHub Project Analyzer -- Tier 1 pipeline (Python-only)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo-url", help="e.g. https://github.com/owner/repo")
    src.add_argument("--local-path", help="path to an already-cloned local repo")
    ap.add_argument("--commit-sha", default=None)
    ap.add_argument("--cache-dir", default=os.path.join(os.path.dirname(__file__), "..", ".cache"))
    ap.add_argument("--out", default=None, help="write JSON result to this file (else stdout)")
    args = ap.parse_args()

    result = run_pipeline(args.repo_url, args.local_path, args.commit_sha, args.cache_dir)

    output = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(output)
        print(f"Wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
