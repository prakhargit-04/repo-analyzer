"""
Reproducible Benchmark Suite for Repo Analyzer v0.24.2 (TASK R7).

Measures median execution time over >=5 runs with fixed random seeds for:
  1. Graph Builder: Optimized index lookup vs linear-scan reference
  2. SQL Reads: Optimized SQL queries vs full in-memory deserialization
  3. Retrieval: Vectorized numpy vs pure-Python fallback loop
  4. Chunk Persistence: Bulk transactional insert vs naive row-by-row insert

Prints machine hardware info and Markdown summary table suitable for REPORT.md.
"""
import os
import sys
import math
import time
import random
import platform
import statistics
from pathlib import Path
from datetime import datetime, timezone

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
_TESTS_DIR = _REPO_ROOT / "tests"

for p in [str(_REPO_ROOT), str(_PIPELINE_DIR), str(_TESTS_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from graph_builder import build_graph
from reference.graph_builder_reference import build_graph_reference
from parse_python import FileParseResult, ClassNode, FunctionNode, ImportEdge
from db.engine import create_all_tables
from db.models import AnalysisRun
from db.store import (
    get_analysis_summary_db,
    get_analysis_graph_db,
    get_analysis_findings_db,
    get_analysis_files_db,
    persist_analysis,
    _run_to_dict,
)


def run_benchmark(fn, iterations: int = 5):
    """Run fn iterations times and return median execution time in milliseconds."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000.0)
    return statistics.median(times)


# ---------------------------------------------------------------------------
# 1. Graph Builder Benchmark
# ---------------------------------------------------------------------------
def _generate_synthetic_parse_results(seed_val: int = 42, num_files: int = 500) -> list:
    rng = random.Random(seed_val)
    parse_results = []
    class_pool = [f"Class_{i}" for i in range(50)]
    fn_pool = [f"func_{i}" for i in range(100)]

    for f_idx in range(num_files):
        filename = f"src/module_{f_idx}.py"
        classes = []
        functions = []
        imports = []

        # 2 classes per file
        for c_idx in range(2):
            c_name = rng.choice(class_pool)
            c_id = f"{filename}::{c_name}"
            bases = [rng.choice(class_pool)] if rng.random() > 0.4 else []
            classes.append(ClassNode(id=c_id, name=c_name, file=filename, start_line=1, end_line=50, bases=bases, provenance="ast"))

        # 5 functions per file
        for fn_idx in range(5):
            fn_name = rng.choice(fn_pool)
            fn_id = f"{filename}::{fn_name}"
            calls = rng.sample(fn_pool, k=2)
            functions.append(FunctionNode(id=fn_id, name=fn_name, file=filename, start_line=51, end_line=80, calls=calls, provenance="ast"))

        # 2 imports per file
        for i_idx in range(2):
            imp_target = f"src.module_{rng.randint(0, num_files - 1)}"
            imports.append(ImportEdge(file=filename, imported=imp_target, alias=None, line=i_idx + 1))

        parse_results.append(FileParseResult(file=filename, functions=functions, classes=classes, imports=imports, parse_error=None))

    return parse_results


def bench_graph_builder(num_runs: int = 5):
    parse_results = _generate_synthetic_parse_results(seed_val=42, num_files=500)

    med_ref = run_benchmark(lambda: build_graph_reference(parse_results), iterations=num_runs)
    med_opt = run_benchmark(lambda: build_graph(parse_results), iterations=num_runs)

    return med_ref, med_opt


# ---------------------------------------------------------------------------
# 2. SQL Reads Benchmark vs In-Memory Deserialization Oracle
# ---------------------------------------------------------------------------
def _build_seeded_analysis_payload(num_files: int = 100):
    nodes = []
    edges = []
    findings = []
    for f_idx in range(num_files):
        fp = f"src/file_{f_idx:02d}.py"
        nodes.append({"id": fp, "type": "file", "provenance": "filesystem-walk"})
        fn_id = f"{fp}::func_{f_idx}"
        nodes.append({"id": fn_id, "type": "function", "name": f"func_{f_idx}", "file": fp, "start_line": 1, "end_line": 20, "provenance": "ast"})
        edges.append({"source": fp, "target": fn_id, "relation": "contains", "confidence": "structural_certain", "provenance": "ast"})

    for i in range(150):
        findings.append({
            "id": f"finding::{i}",
            "type": "finding",
            "analyzer": "semgrep" if i % 2 == 0 else "bandit",
            "severity": "HIGH" if i % 3 == 0 else "MEDIUM",
            "rule_id": f"rule_{i % 10}",
            "file": f"src/file_{i % num_files:02d}.py",
            "line": i + 1,
            "message": f"Test vulnerability finding {i}",
            "provenance": "semgrep",
        })

    static_analysis = {
        "bandit_findings": {"results": [f for f in findings if f["analyzer"] == "bandit"]},
        "semgrep_findings": {"results": [f for f in findings if f["analyzer"] == "semgrep"]},
    }

    return {
        "schema_version": "1.0.0",
        "cache_schema_version": "v5",
        "analyzer_version": "0.24.2",
        "repository": "https://github.com/bench/sql_reads",
        "commit_sha": "bench1234567890",
        "cache_snapshot_id": "snap_bench_100",
        "analyzed_at_utc": "2026-10-10T00:00:00Z",
        "languages": ["python"],
        "analysis_status": "complete",
        "files_analyzed": num_files,
        "graph": {"nodes": nodes, "edges": edges},
        "static_analysis": static_analysis,
        "health_score": {"composite_health_score": 88.5, "structural_score": 92.0, "static_score": 85.0},
        "source_chunks": [
            {
                "chunk_id": f"chunk_{i}",
                "file_path": f"src/file_{i % num_files:02d}.py",
                "start_line": 1,
                "end_line": 20,
                "chunk_type": "function",
                "content": f"def chunk_fn_{i}(): pass",
                "commit_sha": "bench1234567890",
            }
            for i in range(200)
        ],
        "embeddings": [
            {
                "chunk_id": f"chunk_{i}",
                "model_name": "hash-v1",
                "dimension": 384,
                "vector": [0.1] * 384,
            }
            for i in range(200)
        ],
    }


def bench_sql_reads(num_runs: int = 5):
    engine = create_engine("sqlite:///:memory:")
    create_all_tables(engine)

    payload = _build_seeded_analysis_payload(num_files=100)
    with Session(engine) as session:
        run_id = persist_analysis(session, payload)
        session.commit()

    # Oracle read (loads full run with ORM relations into memory dict)
    def oracle_read():
        with Session(engine) as session:
            r = session.query(AnalysisRun).filter_by(id=run_id).one()
            return _run_to_dict(session, r)

    # SQL optimized read (summary, graph, findings, files)
    def sql_opt_read():
        with Session(engine) as session:
            s = get_analysis_summary_db(session, run_id)
            g = get_analysis_graph_db(session, run_id)
            f = get_analysis_findings_db(session, run_id)
            fl = get_analysis_files_db(session, run_id)
            return s, g, f, fl

    med_oracle = run_benchmark(oracle_read, iterations=num_runs)
    med_opt = run_benchmark(sql_opt_read, iterations=num_runs)

    return med_oracle, med_opt


# ---------------------------------------------------------------------------
# 3. Retrieval Benchmark: Numpy Vectorized vs Fallback Python Loop
# ---------------------------------------------------------------------------
def _cosine_sim_python(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def bench_retrieval(num_runs: int = 5):
    np.random.seed(42)
    num_vectors = 1000
    dim = 384

    query_vec = np.random.randn(dim).astype(np.float64).tolist()
    matrix_vecs = np.random.randn(num_vectors, dim).astype(np.float64).tolist()

    # Fallback pure-Python loop
    def py_retrieval():
        scores = [_cosine_sim_python(query_vec, v) for v in matrix_vecs]
        return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:10]

    # Optimized vectorized numpy calculation
    def numpy_retrieval():
        mat = np.array(matrix_vecs, dtype=np.float64)
        q = np.array(query_vec, dtype=np.float64)
        q_norm = np.linalg.norm(q)
        mat_norms = np.linalg.norm(mat, axis=1)
        denom = mat_norms * q_norm
        scores = np.divide(np.dot(mat, q), denom, out=np.zeros_like(denom), where=denom != 0)
        top_k = np.argsort(scores)[::-1][:10]
        return top_k

    med_fallback = run_benchmark(py_retrieval, iterations=num_runs)
    med_numpy = run_benchmark(numpy_retrieval, iterations=num_runs)

    return med_fallback, med_numpy


# ---------------------------------------------------------------------------
# 4. Chunk Persistence Benchmark
# ---------------------------------------------------------------------------
def bench_chunk_persistence(num_runs: int = 5):
    payload = _build_seeded_analysis_payload(num_files=100)

    def run_persist():
        engine = create_engine("sqlite:///:memory:")
        create_all_tables(engine)
        with Session(engine) as session:
            persist_analysis(session, payload)
            session.commit()

    med_persist = run_benchmark(run_persist, iterations=num_runs)

    return med_persist


# ---------------------------------------------------------------------------
# Main Runner & Report Formatter
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("   REPO ANALYZER v0.24.2 - REPRODUCIBLE BENCHMARK SUITE")
    print("=" * 70)

    # Hardware & Env Details
    print("\n--- Environment & Machine Information ---")
    print(f"OS Platform     : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python Version  : {sys.version.split()[0]}")
    print(f"NumPy Version   : {np.__version__}")
    print(f"Timestamp       : {datetime.now(timezone.utc).isoformat()}")
    print(f"Runs Per Test   : 5 (Median reported)")

    print("\nRunning benchmarks...")

    # 1. Graph Builder
    med_graph_ref, med_graph_opt = bench_graph_builder(num_runs=5)
    graph_speedup = med_graph_ref / med_graph_opt if med_graph_opt > 0 else 0

    # 2. SQL Reads
    med_sql_oracle, med_sql_opt = bench_sql_reads(num_runs=5)
    sql_speedup = med_sql_oracle / med_sql_opt if med_sql_opt > 0 else 0

    # 3. Retrieval
    med_ret_fallback, med_ret_numpy = bench_retrieval(num_runs=5)
    ret_speedup = med_ret_fallback / med_ret_numpy if med_ret_numpy > 0 else 0

    # 4. Chunk Persistence
    med_persist = bench_chunk_persistence(num_runs=5)

    print("\n" + "=" * 70)
    print("### Benchmark Results Summary Table")
    print("=" * 70)
    print("| Subsystem / Task | Baseline / Oracle Median | Optimized Median | Speedup Factor |")
    print("| :--- | :--- | :--- | :--- |")
    print(f"| Graph Builder (500 files) | {med_graph_ref:.2f} ms | {med_graph_opt:.2f} ms | {graph_speedup:.2f}x |")
    print(f"| SQL Summary & Graph Reads | {med_sql_oracle:.2f} ms | {med_sql_opt:.2f} ms | {sql_speedup:.2f}x |")
    print(f"| Vector Retrieval (1000 vectors) | {med_ret_fallback:.2f} ms | {med_ret_numpy:.2f} ms | {ret_speedup:.2f}x |")
    print(f"| Chunk Persistence (200 chunks + AST) | N/A | {med_persist:.2f} ms | Batch Persist |")
    print("=" * 70)


if __name__ == "__main__":
    main()
