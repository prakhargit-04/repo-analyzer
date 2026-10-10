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
import time
from datetime import datetime, timezone
from typing import Callable, Optional


sys.path.insert(0, os.path.dirname(__file__))
import clone
from parser_interface import parse_repository
import static_analysis
from graph_builder import build_graph, graph_summary
from health_score import compute_health_score
from chunker import generate_repository_chunks, SOURCE_CHUNKER_VERSION, SOURCE_CHUNK_SCHEMA_VERSION
from embeddings import EMBEDDING_PIPELINE_VERSION
from embeddings_stage import generate_source_embeddings
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
    """Writes cache file atomically using a temporary file and os.replace.

    On Windows, os.replace can raise PermissionError (WinError 32 or Access Denied)
    if another thread/process briefly holds the destination file open. We use a bounded
    retry policy with exponential backoff so transient contention is handled safely.

    The temporary file is created in the same directory as the target so that
    os.replace is always an intra-filesystem rename (atomic on POSIX).  We use
    ``tempfile.mkstemp`` rather than a manually-constructed path with PID/TID
    suffix to avoid exceeding the Windows MAX_PATH (260-char) limit when the
    cache directory path itself is already long.
    """
    cache_dir = os.path.dirname(cache_path) or "."
    os.makedirs(cache_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, sort_keys=True)
        fd = -1  # fdopen took ownership; fd is now closed

        max_retries = 5
        for attempt in range(max_retries):
            try:
                os.replace(temp_path, cache_path)
                break
            except PermissionError:
                if attempt == max_retries - 1:
                    raise
                time.sleep(0.02 * (2 ** attempt))
    except Exception:
        if fd != -1:
            # mkstemp fd wasn't handed to fdopen yet; close it manually
            try:
                os.close(fd)
            except OSError:
                pass
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
    persist_to_db: bool = False,
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
            resolved_sha = clone.clone_repository(repo_url, repo_root, commit_sha)
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
            notify("chunking", "completed", "Loaded from file cache")
            notify("embedding", "completed", "Loaded from file cache")
            return cached

        notify("parsing", "running")
        parse_results = parse_repository(repo_root)
        parse_results.sort(key=lambda r: r.file)
        parsed_files_rel = [r.file for r in parse_results if not r.parse_error]
        notify("parsing", "completed", f"{len(parse_results)} files parsed")

        notify("analyzing", "running")
        analysis = static_analysis.analyze_repository(repo_root, parsed_files_rel)
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

        notify("chunking", "running")
        source_chunks = generate_repository_chunks(repo_root, parse_results, commit_sha=resolved_sha)
        notify("chunking", "completed", f"{len(source_chunks)} chunks generated")

        notify("embedding", "running")
        embeddings, emb_status = generate_source_embeddings(
            source_chunks,
            repo_url=repo_url or local_path or "unknown",
            commit_sha=resolved_sha,
        )
        notify("embedding", "completed", f"{len(embeddings)} embeddings generated ({emb_status['status']})")

        result = {
            "schema_version": SCHEMA_VERSION,
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "analyzer_version": ANALYZER_VERSION,
            "chunker_version": SOURCE_CHUNKER_VERSION,
            "embedding_pipeline_version": EMBEDDING_PIPELINE_VERSION,
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

            "files_analyzed": len(parsed_files_rel),
            "parse_errors": parse_errors,
            "static_analysis": analysis,
            "knowledge_graph_summary": summary,
            "knowledge_graph": graph_data,
            "health_score": health,
            "source_chunks": source_chunks,
            "source_embeddings": embeddings,
            "embedding_status": emb_status,
        }

        save_cache_atomic(cache_path, result)
        if persist_to_db:
            _try_persist_to_db(result)
        return result
    finally:
        if cleanup_dir and os.path.exists(cleanup_dir):
            shutil.rmtree(cleanup_dir, ignore_errors=True)



def main():
    ap = argparse.ArgumentParser(description="GitHub Project Analyzer -- Multi-language Tier 1 pipeline")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo-url", help="e.g. https://github.com/owner/repo")
    src.add_argument("--local-path", help="path to an already-cloned local repo")
    ap.add_argument("--commit-sha", default=None)
    from util import get_cache_dir
    ap.add_argument("--cache-dir", default=get_cache_dir())
    ap.add_argument("--out", default=None, help="write JSON result to this file (else stdout)")
    args = ap.parse_args()

    result = run_pipeline(
        args.repo_url,
        args.local_path,
        args.commit_sha,
        args.cache_dir,
        persist_to_db=bool(os.environ.get("DATABASE_URL")),
    )

    output = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(output)
        print(f"Wrote {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
