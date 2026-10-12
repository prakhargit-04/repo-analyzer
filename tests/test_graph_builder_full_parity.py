"""
v0.24.6 - FULL graph equivalence (every edge type, including ``calls``) against the faithful
pre-optimisation reference ``tests/reference/graph_builder_original.py``.

Why this exists: the older oracle (test_graph_builder_oracle.py, reference ``graph_builder_reference.py``)
compares only structural edges because that reference implements a simplified call-resolution
algorithm. It therefore cannot prove the optimised builder preserves call edges, which are the bulk of
the graph (3,000 of ~3,800 edges on the 500-function benchmark fixture).
"""
from __future__ import annotations

import json
import os
import random
import sys

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
for _p in (_ROOT, os.path.join(_ROOT, "pipeline"), os.path.dirname(__file__), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from graph_builder import build_graph
from parse_python import ClassNode, FileParseResult, FunctionNode, ImportEdge
from reference.graph_builder_original import build_graph as build_graph_original
import bench_graph_large as bench


def _ser(g):
    return bench.serialize(g)


def _random_repo(seed: int) -> list:
    """Small repos engineered for ambiguity: duplicate class names inside one file and across files,
    same-named methods, inheritance, imports, and self./Class./new/module-qualified calls."""
    r = random.Random(seed)
    nf = r.randint(2, 6)
    names = ["A", "B", "C", "Dup"]
    fnames = ["run", "go", "helper", "init", "greet"]
    files = []
    for f in range(nf):
        fp = f"m{f}.py"
        classes = [
            ClassNode(id=f"{fp}::{r.choice(names)}:{k * 20 + 1}", name="", file=fp, start_line=k * 20 + 1,
                      end_line=k * 20 + 19, bases=[r.choice(names)] if r.random() < 0.3 else [], provenance="ast")
            for k in range(r.randint(0, 4))
        ]
        for c in classes:  # name must match the id (as the parser would produce)
            c.name = c.id.split("::")[1].split(":")[0]
        fns = []
        for k in range(r.randint(1, 6)):
            owner = r.choice([c.name for c in classes]) if classes and r.random() < 0.6 else None
            calls = [
                r.choice(["new " + r.choice(names), "self." + r.choice(fnames), "helper",
                          "super." + r.choice(fnames), f"{r.choice(names)}.{r.choice(fnames)}",
                          f"m{r.randint(0, nf - 1)}.{r.choice(fnames)}"])
                for _ in range(r.randint(0, 4))
            ]
            fns.append(FunctionNode(id=f"{fp}::{r.choice(fnames)}_{k}:{k + 100}", name=r.choice(fnames), file=fp,
                                    start_line=100 + k, end_line=105 + k, class_owner=owner, calls=calls,
                                    provenance="ast"))
        imps = [ImportEdge(file=fp, imported=f"m{r.randint(0, nf - 1)}.{r.choice(names)}", alias=None, line=1)
                for _ in range(r.randint(0, 2))]
        files.append(FileParseResult(file=fp, classes=classes, functions=fns, imports=imps, parse_error=None))
    return files


@pytest.mark.parametrize("seed", range(400))
def test_random_repos_are_byte_identical_to_original(seed):
    data = _random_repo(seed)
    assert _ser(build_graph(data)) == _ser(build_graph_original(data))


@pytest.mark.parametrize("n_functions", [500, 2000])
def test_benchmark_fixture_is_byte_identical_including_call_edges(n_functions):
    data = bench.make_fixture(n_functions)
    g_new, g_old = build_graph(data), build_graph_original(data)
    nodes_new, edges_new = _ser(g_new)
    nodes_old, edges_old = _ser(g_old)
    assert nodes_new == nodes_old
    assert edges_new == edges_old
    n_calls = sum(1 for e in edges_new if json.loads(e[2]).get("relation") == "calls")
    assert n_calls > 1000, "fixture must actually exercise call resolution"


def test_empty_repo_and_single_file():
    assert _ser(build_graph([])) == _ser(build_graph_original([]))
    data = _random_repo(7)[:1]
    assert _ser(build_graph(data)) == _ser(build_graph_original(data))
