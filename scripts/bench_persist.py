"""
Persistence benchmark on REAL pipeline output (v0.24.6).

Why this exists: the synthetic payload in ``scripts/bench.py`` used the keys ``graph`` and
``embeddings`` while ``persist_analysis`` reads ``knowledge_graph`` and ``source_embeddings``, so
that benchmark persisted 200 chunks and **zero** embeddings, graph nodes and findings. This script
measures what the production pipeline actually produces and *asserts the row counts* so an empty
write can never be benchmarked again.

Method:
  1. Run the real pipeline (parse -> graph -> chunk -> embed with the deterministic test provider) on this
     repository's own ``pipeline/`` directory. Analyzers are stubbed with a fixed all-success result
     (their cost is not what is being measured, and it keeps the run offline and deterministic).
  2. Persist that result into a fresh in-memory SQLite database, ``--runs`` times (median reported),
     verifying row counts match the input every time.
  3. Repeat with the chunks/embeddings replicated up to ``--scale-chunks`` rows to show how cost grows.

Usage:
    python scripts/bench_persist.py [--runs 5] [--scale-chunks 2500]
"""
from __future__ import annotations

import argparse
import copy
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "pipeline")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import main as pipeline_main  # noqa: E402
import static_analysis  # noqa: E402
from db.engine import create_all_tables  # noqa: E402
from db.models import GraphEdge, GraphNode, SourceChunk, SourceEmbedding  # noqa: E402
from db.store import persist_analysis  # noqa: E402


def _stub_analysis(repo_root, parsed_files_rel=None, **kwargs):
    ok = {"status": "success", "results": []}
    return {
        "scope_policy": "production_code_only",
        "production_files_analyzed": len(parsed_files_rel or []),
        "test_files_excluded": 0,
        "complexity": dict(ok), "maintainability": dict(ok), "security": dict(ok),
        "semgrep_findings": dict(ok), "gitleaks_findings": dict(ok), "osv_vulnerabilities": dict(ok),
    }


def real_result() -> dict:
    static_analysis.analyze_repository = _stub_analysis
    return pipeline_main.run_pipeline(
        repo_url=None, local_path=str(_ROOT / "pipeline"), commit_sha=None,
        cache_dir=tempfile.mkdtemp(prefix="bench_persist_"), persist_to_db=False,
    )


def scale_chunks(result: dict, target: int) -> dict:
    """Replicate chunks and their embeddings (with unique ids) up to ``target`` rows."""
    out = copy.deepcopy(result)
    base_c, base_e = result["source_chunks"], result["source_embeddings"]
    emb_by_chunk = {e["chunk_id"]: e for e in base_e}
    chunks, embs, i = [], [], 0
    while len(chunks) < target:
        c = copy.deepcopy(base_c[i % len(base_c)])
        e = copy.deepcopy(emb_by_chunk[c["chunk_id"]])
        suffix = f"#{i // len(base_c)}"
        c["chunk_id"] += suffix
        e["chunk_id"] = c["chunk_id"]
        chunks.append(c)
        embs.append(e)
        i += 1
    out["source_chunks"], out["source_embeddings"] = chunks, embs
    return out


def persist_once(result: dict) -> float:
    engine = create_engine("sqlite:///:memory:")
    create_all_tables(engine)
    with Session(engine) as s:
        t0 = time.perf_counter()
        persist_analysis(s, result)
        s.commit()
        dt = (time.perf_counter() - t0) * 1000.0
        # Guard: never benchmark an empty write.
        counts = {
            "chunks": s.execute(select(func.count()).select_from(SourceChunk)).scalar(),
            "embeddings": s.execute(select(func.count()).select_from(SourceEmbedding)).scalar(),
            "nodes": s.execute(select(func.count()).select_from(GraphNode)).scalar(),
            "edges": s.execute(select(func.count()).select_from(GraphEdge)).scalar(),
        }
    engine.dispose()
    expect = {
        "chunks": len(result["source_chunks"]),
        "embeddings": len(result["source_embeddings"]),
        "nodes": len(result["knowledge_graph"]["nodes"]),
        "edges": len(result["knowledge_graph"]["edges"]),
    }
    if counts != expect:
        raise SystemExit(f"ROW COUNT MISMATCH - benchmark invalid: persisted {counts}, expected {expect}")
    return dt


def bench(label: str, result: dict, runs: int) -> None:
    persist_once(result)  # warm-up (untimed)
    times = [persist_once(result) for _ in range(runs)]
    n = len(result["source_chunks"])
    med = statistics.median(times)
    print(f"{label}: {n} chunks + {len(result['source_embeddings'])} embeddings + "
          f"{len(result['knowledge_graph']['nodes'])} nodes + {len(result['knowledge_graph']['edges'])} edges")
    print(f"  runs(ms): {[round(t, 1) for t in times]}")
    print(f"  median {med:.1f} ms | min {min(times):.1f} ms | ~{med / n * 1000:.0f} us per chunk (incl. its embedding)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--scale-chunks", type=int, default=2500)
    args = ap.parse_args()
    print(f"python {platform.python_version()} | {platform.platform()} | {platform.machine()} | "
          f"sqlite in-memory | runs={args.runs}")
    res = real_result()
    bench("REAL pipeline output (this repo's pipeline/)", res, args.runs)
    bench(f"replicated to {args.scale_chunks} chunks", scale_chunks(res, args.scale_chunks), args.runs)


if __name__ == "__main__":
    main()
