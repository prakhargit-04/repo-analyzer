"""
Sub-task 6.2: Graph Builder Oracle Differential Test against reference linear-scan implementation.
"""
import json
import random
import sys
import time
import pytest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_DIR = _REPO_ROOT / "pipeline"
for _p in [str(_REPO_ROOT), str(_PIPELINE_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from graph_builder import build_graph
from reference.graph_builder_reference import build_graph_reference
from parse_python import FileParseResult, ClassNode, FunctionNode, ImportEdge


def serialize_graph(g, exclude_node_prefixes: tuple | None = None):
    """Serialize a graph to a canonical JSON byte-string for comparison.

    Parameters
    ----------
    exclude_node_prefixes:
        If given, nodes whose IDs start with any of these prefixes—and all
        edges incident to those nodes—are excluded before serialisation.
        This lets the differential test compare the shared structural projection
        when the optimised implementation intentionally emits extra nodes
        (e.g. ``ambiguous_call::*``, ``unresolved_call::*``) that the reference
        oracle omits.
    """
    nodes = []
    excluded = set()
    for node_id, data in sorted(g.nodes(data=True), key=lambda x: str(x[0])):
        if exclude_node_prefixes and any(str(node_id).startswith(p) for p in exclude_node_prefixes):
            excluded.add(node_id)
            continue
        d = {"id": node_id}
        d.update(data)
        nodes.append(d)
    edges = []
    for u, v, data in sorted(g.edges(data=True), key=lambda x: (str(x[0]), str(x[1]), json.dumps(x[2], sort_keys=True))):
        if u in excluded or v in excluded:
            continue
        d = {"source": u, "target": v}
        d.update(data)
        edges.append(d)
    return json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True, indent=2).encode("utf-8")


def _generate_random_repo(seed: int) -> list:
    rng = random.Random(seed)
    num_files = rng.randint(3, 8)
    parse_results = []

    class_pool = ["BaseModel", "Config", "Runner", "Handler", "Worker", "Service"]
    fn_pool = ["process", "run", "handle", "compute", "execute", "setup"]

    for f_idx in range(num_files):
        filename = f"pkg/module_{f_idx}.py"
        classes = []
        functions = []
        imports = []

        # Classes
        num_classes = rng.randint(1, 3)
        for c_idx in range(num_classes):
            c_name = rng.choice(class_pool)
            c_id = f"{filename}::{c_name}"
            bases = [rng.choice(class_pool)] if rng.random() > 0.5 else []
            classes.append(ClassNode(id=c_id, name=c_name, file=filename, start_line=1, end_line=30, bases=bases, provenance="ast"))

        # Functions
        num_fns = rng.randint(2, 5)
        for fn_idx in range(num_fns):
            fn_name = rng.choice(fn_pool)
            fn_id = f"{filename}::{fn_name}"
            class_owner = rng.choice([c.name for c in classes]) if (classes and rng.random() > 0.4) else None
            calls = []
            if rng.random() > 0.3:
                calls.append(f"self.{rng.choice(fn_pool)}")
            if rng.random() > 0.3:
                calls.append(rng.choice(fn_pool))
            functions.append(FunctionNode(id=fn_id, name=fn_name, file=filename, start_line=35, end_line=50, class_owner=class_owner, calls=calls, provenance="ast"))

        # Imports
        if f_idx > 0 and rng.random() > 0.3:
            imported_mod = f"pkg.module_{rng.randint(0, f_idx - 1)}"
            imports.append(ImportEdge(file=filename, imported=imported_mod, alias=None, line=1, provenance="ast"))

        parse_results.append(FileParseResult(file=filename, classes=classes, functions=functions, imports=imports, parse_error=None))

    return parse_results


def _extract_graph(g, exclude_node_prefixes=("ambiguous_call::", "unresolved_call::")):
    """Return (node_set, structural_edges, call_edges) from a graph, excluding disambiguation nodes."""
    excluded = {nid for nid in g.nodes() if any(str(nid).startswith(p) for p in exclude_node_prefixes)}
    node_set = frozenset(str(nid) for nid in g.nodes() if nid not in excluded)
    structural_edges = set()
    call_edges = set()
    for u, v, data in g.edges(data=True):
        if u in excluded or v in excluded:
            continue
        rel = data.get("relation", "")
        key = (str(u), str(v), rel)
        if rel == "calls":
            call_edges.add(key)
        else:
            structural_edges.add(key)
    return node_set, structural_edges, call_edges


def test_graph_builder_differential_parity_400_seed():
    """Differential oracle test over 400 seeded random repos.

    Checks that the optimised ``build_graph`` produces the same *structural*
    topology as the linear-scan reference implementation:
    - Same set of nodes (excluding disambiguation nodes added only by the
      optimised path: ``ambiguous_call::*``, ``unresolved_call::*``).
    - Same non-call edges (contains, imports, depends_on, inherits).

    Call edges are deliberately *not* compared: the optimised version uses
    multi-step cross-file resolution (steps 4a–4c) which both resolves more
    cross-file calls and avoids self-calls, producing a legitimately different
    but more accurate call graph than the linear-scan reference.
    """
    node_failures = 0
    structural_failures = 0

    for seed in range(400):
        parse_results = _generate_random_repo(seed + 1000)
        g_ref = build_graph_reference(parse_results)
        g_curr = build_graph(parse_results)

        ref_nodes, ref_struct, _ = _extract_graph(g_ref)
        curr_nodes, curr_struct, _ = _extract_graph(g_curr)

        if ref_nodes != curr_nodes:
            node_failures += 1
        if ref_struct != curr_struct:
            structural_failures += 1

    assert node_failures == 0, f"Node sets differed on {node_failures}/400 repos"
    assert structural_failures == 0, f"Structural edges differed on {structural_failures}/400 repos"


def test_graph_builder_performance_class_heavy():
    """Performance timing test: 2000 files x 3 functions builds within generous threshold (5s)."""
    parse_results = []
    for i in range(2000):
        filename = f"src/file_{i}.py"
        fns = [
            FunctionNode(id=f"{filename}::fn_{j}", name=f"fn_{j}", file=filename, start_line=j*10, end_line=j*10+5, calls=[f"fn_{(j+1)%3}"], provenance="ast")
            for j in range(3)
        ]
        parse_results.append(FileParseResult(file=filename, classes=[], functions=fns, imports=[], parse_error=None))

    t0 = time.perf_counter()
    g = build_graph(parse_results)
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, f"Graph build took {elapsed:.2f}s, exceeding 5.0s threshold"
    assert g.number_of_nodes() > 2000
