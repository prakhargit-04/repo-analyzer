"""
Large-fixture graph-builder benchmark (v0.24.6).

Compares the production ``build_graph`` with the faithful pre-optimisation original in
``tests/reference/graph_builder_original.py`` on a deterministic synthetic repository of
~2,000 functions (default), plus a smaller and a larger scale to show how cost grows.

Order of operations (per scale):
  1. Build the same input once, verify both implementations return byte-identical graphs
     (sorted nodes + edges, JSON with sorted keys). Timing is skipped if they differ.
  2. One untimed warm-up run of each implementation.
  3. N timed runs, alternating implementations (so drift hits both equally). Raw times,
     median and min are printed.

Usage:
    python scripts/bench_graph_large.py                # scales 500 / 2000 / 8000 functions, 7 runs
    python scripts/bench_graph_large.py --runs 9 --scales 2000

Exit code 1 if the implementations disagree.
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import statistics
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "pipeline"), str(_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from graph_builder import build_graph  # noqa: E402
from parse_python import ClassNode, FileParseResult, FunctionNode, ImportEdge  # noqa: E402
from reference.graph_builder_original import build_graph as build_graph_reference  # noqa: E402

FNS_PER_FILE = 10


def make_fixture(n_functions: int, seed: int = 20260611) -> list:
    """Deterministic repo: files of 10 functions, 2 classes per file, unique node ids.

    Calls mix every resolution path the builder has: bare names (same-file / cross-file),
    ``self.x`` (enclosing class), ``Class.x`` / ``new Class`` (class resolution via same-file,
    imports and global name), and module-qualified ``module.func`` calls. Some class names are
    reused across files so name resolution has real ambiguity to work through.
    """
    rng = random.Random(seed)
    n_files = max(1, n_functions // FNS_PER_FILE)
    n_class_names = max(10, int(n_files * 2 * 0.8))  # ~20% of class names collide across files
    class_names = [f"Class{i}" for i in range(n_class_names)]
    shared_fn_names = [f"shared_{i}" for i in range(60)]  # names that exist in many files

    results = []
    for f in range(n_files):
        fname = f"src/pkg{f % 20}/module_{f}.py"
        classes = []
        for c in range(2):
            cname = class_names[(f * 2 + c) % n_class_names]
            classes.append(
                ClassNode(
                    id=f"{fname}::{cname}:{c * 100 + 1}",
                    name=cname,
                    file=fname,
                    start_line=c * 100 + 1,
                    end_line=c * 100 + 90,
                    bases=[rng.choice(class_names)] if rng.random() < 0.35 else [],
                    provenance="ast",
                )
            )
        fns = []
        for i in range(FNS_PER_FILE):
            name = shared_fn_names[(f + i) % len(shared_fn_names)] if i < 3 else f"fn_{f}_{i}"
            owner = classes[i % 2].name if i % 2 == 0 else None
            calls = [
                rng.choice(shared_fn_names),
                f"fn_{f}_{rng.randrange(FNS_PER_FILE)}",
                f"self.fn_{f}_{rng.randrange(FNS_PER_FILE)}",
                f"{rng.choice(class_names)}.{rng.choice(shared_fn_names)}",
                f"new {rng.choice(class_names)}",
                f"module_{rng.randrange(n_files)}.{rng.choice(shared_fn_names)}",
            ]
            fns.append(
                FunctionNode(
                    id=f"{fname}::{name}:{200 + i * 10}",
                    name=name,
                    file=fname,
                    start_line=200 + i * 10,
                    end_line=205 + i * 10,
                    class_owner=owner,
                    calls=calls,
                    provenance="ast",
                )
            )
        imports = [
            ImportEdge(
                file=fname,
                imported=f"src.pkg{rng.randrange(20)}.module_{rng.randrange(n_files)}.{rng.choice(class_names)}",
                alias=None,
                line=k + 1,
            )
            for k in range(3)
        ]
        results.append(FileParseResult(file=fname, functions=fns, classes=classes, imports=imports, parse_error=None))
    return results


def serialize(g) -> tuple:
    nodes = sorted([str(n), json.dumps(d, sort_keys=True, default=str)] for n, d in g.nodes(data=True))
    edges = sorted([str(u), str(v), json.dumps(d, sort_keys=True, default=str)] for u, v, d in g.edges(data=True))
    return nodes, edges


def timed(fn, arg) -> float:
    t0 = time.perf_counter()
    fn(arg)
    return (time.perf_counter() - t0) * 1000.0


def bench_scale(n_functions: int, runs: int) -> bool:
    data = make_fixture(n_functions)
    n_fn = sum(len(r.functions) for r in data)
    n_cls = sum(len(r.classes) for r in data)
    n_calls = sum(len(fn.calls) for r in data for fn in r.functions)
    ref_graph, opt_graph = build_graph_reference(data), build_graph(data)
    equal = serialize(ref_graph) == serialize(opt_graph)
    print(f"\n=== {n_fn} functions, {n_cls} classes, {n_calls} call sites, "
          f"{ref_graph.number_of_nodes()} nodes / {ref_graph.number_of_edges()} edges ===")
    print(f"graph equivalence (reference vs production): {'IDENTICAL' if equal else 'DIFFERENT'}")
    if not equal:
        return False

    build_graph_reference(data)  # warm-up (untimed)
    build_graph(data)
    ref_t, opt_t = [], []
    for _ in range(runs):  # alternate so drift affects both
        ref_t.append(timed(build_graph_reference, data))
        opt_t.append(timed(build_graph, data))
    mr, mo = statistics.median(ref_t), statistics.median(opt_t)
    print(f"reference  runs(ms): {[round(x, 1) for x in ref_t]}")
    print(f"production runs(ms): {[round(x, 1) for x in opt_t]}")
    print(f"median  reference {mr:.1f} ms | production {mo:.1f} ms | speedup {mr / mo:.2f}x "
          f"| min reference {min(ref_t):.1f} ms | min production {min(opt_t):.1f} ms")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--scales", type=int, nargs="+", default=[500, 2000, 8000])
    args = ap.parse_args()
    print(f"python {platform.python_version()} | {platform.platform()} | {platform.machine()} | "
          f"runs={args.runs} | seed=20260611 | functions/file={FNS_PER_FILE}")
    ok = all([bench_scale(n, args.runs) for n in args.scales])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
