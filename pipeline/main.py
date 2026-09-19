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
from typing import Callable, Optional


sys.path.insert(0, os.path.dirname(__file__))
from clone import clone_repository
from parser_interface import parse_repository
from static_analysis import analyze_repository
from graph_builder import build_graph, graph_summary
from health_score import compute_health_score
from util import resolve_snapshot_id, try_git_head_sha, build_cache_key, CACHE_SCHEMA_VERSION, ANALYZER_VERSION, SCHEMA_VERSION

# S14: optional DB persistence -- only imported when DATABASE_URL is set
def _try_persist_to_db(result: dict) -> None:
    """If DATABASE_URL env var is set, persist the analysis result to the database."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return
    try:
        from db.engine import get_engine, create_all_tables, get_session_factory
        from db.store import persist_analysis
        engine = get_engine(db_url)
        create_all_tables(engine)
        SessionLocal = get_session_factory(engine)
        with SessionLocal() as session:
            run_id = persist_analysis(session, result)
            session.commit()
            print(f"[db] Persisted analysis run {run_id}", file=sys.stderr)
    except Exception as exc:
        # DB persistence failure must never break the pipeline output.
        print(f"[db warning] Could not persist to database: {exc}", file=sys.stderr)


def load_cache(cache_path: str) -> dict | None:
    """Loads cached result if present and valid; removes corrupted cache files safely."""
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict) and "schema_version" in data and "knowledge_graph" in data:
                return data
    except Exception as exc:
        print(f"[cache warning] Removing corrupted cache file {cache_path}: {exc}", file=sys.stderr)
        try:
            os.remove(cache_path)
        except OSError:
            pass
    return None


def save_cache_atomic(cache_path: str, result: dict) -> None:
    """Writes cache file atomically using a temporary file and os.replace."""
    cache_dir = os.path.dirname(cache_path)
    os.makedirs(cache_dir, exist_ok=True)
    temp_path = f"{cache_path}.tmp.{os.getpid()}"
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        os.replace(temp_path, cache_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def run_pipeline(
    repo_url: str | None,
    local_path: str | None,
    commit_sha: str | None,
    cache_dir: str,
    stage_callback: Callable[[str, str, Optional[str]], None] | None = None,
) -> dict:
    cleanup_dir = None
    is_fresh_clone = False

    def notify(stage: str, status: str, detail: str | None = None):
        if stage_callback:
            try:
                stage_callback(stage, status, detail)
            except Exception as cb_exc:
                print(f"[stage callback warning] {stage} ({status}) failed: {cb_exc}", file=sys.stderr)

    if local_path:
        if not os.path.exists(local_path):
            raise ValueError(f"Local repository path does not exist: '{local_path}'")
        repo_root = os.path.abspath(local_path)
        git_sha = try_git_head_sha(repo_root)
        resolved_sha = git_sha or "not-a-git-repo"
    elif repo_url:
        cleanup_dir = tempfile.mkdtemp(prefix="gha_repo_")
        repo_root = os.path.join(cleanup_dir, "repo")
    else:
        raise ValueError("Either repo_url or local_path must be provided")

    try:
        notify("cloning", "running")
        if repo_url:
            resolved_sha = clone_repository(repo_url, repo_root, commit_sha)
            is_fresh_clone = True
        notify("cloning", "completed")

        snapshot_id = resolve_snapshot_id(repo_root, is_fresh_clone, resolved_sha)
        versioned_key = build_cache_key(snapshot_id)
        repo_identifier = os.path.basename(os.path.normpath(local_path or repo_url or "repo"))
        cache_key = f"{repo_identifier}@{versioned_key}"
        cache_path = os.path.join(cache_dir, f"{cache_key.replace('/', '_')}.json")

        cached = load_cache(cache_path)
        if cached is not None:
            print(f"[cache hit] {cache_path}", file=sys.stderr)
            notify("parsing", "completed", "Loaded from file cache")
            notify("analyzing", "completed", "Loaded from file cache")
            notify("graph-building", "completed", "Loaded from file cache")
            notify("scoring", "completed", "Loaded from file cache")
            notify("embedding", "skipped", "Skipped until S20")
            return cached

        notify("parsing", "running")
        parse_results = parse_repository(repo_root)
        parse_results.sort(key=lambda r: r.file)
        py_files_rel = [r.file for r in parse_results if not r.parse_error]
        notify("parsing", "completed", f"{len(parse_results)} files parsed")

        notify("analyzing", "running")
        analysis = analyze_repository(repo_root, py_files_rel)
        notify("analyzing", "completed")

        notify("graph-building", "running")
        g = build_graph(parse_results, static_analysis=analysis)
        summary = graph_summary(g)

        nodes = sorted(
            [{"id": node_id, **attributes} for node_id, attributes in g.nodes(data=True)],
            key=lambda n: str(n["id"])
        )
        edges = sorted(
            [{"source": source, "target": target, **attributes} for source, target, attributes in g.edges(data=True)],
            key=lambda e: (
                str(e["source"]),
                str(e["target"]),
                str(e.get("relation", "")),
                str(e.get("raw_call", "")),
                str(e.get("base_name", "")),
                str(e.get("imported_module", "")),
                str(e.get("rule_id", "")),
                str(e.get("line", "")),
            )
        )
        graph_data = {"nodes": nodes, "edges": edges}
        notify("graph-building", "completed", f"{len(nodes)} nodes, {len(edges)} edges")

        notify("scoring", "running")
        health = compute_health_score(analysis)
        parse_errors = sorted(
            [{"file": r.file, "error": r.parse_error} for r in parse_results if r.parse_error],
            key=lambda pe: pe["file"]
        )
        notify("scoring", "completed", f"Status: {health['status']}")

        notify("embedding", "skipped", "Skipped until S20")

        result = {
            "schema_version": SCHEMA_VERSION,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "analyzer_version": ANALYZER_VERSION,
            "repository": repo_url or local_path,
            "commit_sha": resolved_sha,
            "cache_snapshot_id": snapshot_id,
            "cache_key_basis": "git_sha (fresh clone, trusted)" if is_fresh_clone
                               else "content_hash (local path -- git HEAD alone is not "
                                    "trusted because working tree may have uncommitted changes)",
            "analyzed_at_utc": datetime.now(timezone.utc).isoformat(),
            "languages": sorted(list({
                "python" if r.file.endswith(".py")
                else "java" if r.file.endswith(".java")
                else "javascript" if r.file.endswith((".js", ".jsx"))
                else "typescript" if r.file.endswith((".ts", ".tsx"))
                else "unknown"
                for r in parse_results if not r.parse_error
            } or {"python"})),
            "analysis_status": health["status"],

            "files_analyzed": len(py_files_rel),
            "parse_errors": parse_errors,
            "static_analysis": analysis,
            "knowledge_graph_summary": summary,
            "knowledge_graph": graph_data,
            "health_score": health,
        }

        save_cache_atomic(cache_path, result)
        _try_persist_to_db(result)
        return result
    finally:
        if cleanup_dir and os.path.exists(cleanup_dir):
            shutil.rmtree(cleanup_dir, ignore_errors=True)



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

    output = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(output)
        print(f"Wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
