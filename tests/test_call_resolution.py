"""
Unit and integration tests for Session 12: Enhanced Call Resolution Engine.
Verifies accuracy, cross-file resolution, alias handling, receiver resolution,
inheritance resolution, constructors/new expressions, ambiguity preservation,
confidence classification, and determinism across Python, Java, JS, and TS.
"""
import os
import tempfile
import json
import pytest
from pipeline.parser_interface import parse_repository, FileParseResult, ClassNode, FunctionNode, ImportEdge
from pipeline.graph_builder import build_graph, graph_summary
from pipeline.main import run_pipeline


def test_same_file_function_call_resolution():
    """Verify same-file direct call resolution to high_confidence."""
    target = FunctionNode(id="app.py::helper:1", name="helper", file="app.py", start_line=1, end_line=5)
    caller = FunctionNode(id="app.py::main:10", name="main", file="app.py", start_line=10, end_line=15, calls=["helper"])
    fr = FileParseResult(file="app.py", functions=[target, caller], classes=[], imports=[])

    g = build_graph([fr])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert u == "app.py::main:10"
    assert v == "app.py::helper:1"
    assert d["confidence"] == "high_confidence"
    assert d["provenance"] == "graph_builder:same_file_call_resolution"


def test_cross_file_python_imported_call_resolution():
    """Verify imported cross-file call resolution via import tracing."""
    utils_fn = FunctionNode(id="pkg/utils.py::help:1", name="help", file="pkg/utils.py", start_line=1, end_line=5)
    fr_utils = FileParseResult(file="pkg/utils.py", functions=[utils_fn], classes=[], imports=[])

    main_fn = FunctionNode(id="main.py::run:1", name="run", file="main.py", start_line=1, end_line=10, calls=["help"])
    fr_main = FileParseResult(
        file="main.py",
        functions=[main_fn],
        classes=[],
        imports=[ImportEdge(file="main.py", imported="pkg.utils.help", alias=None, line=1)]
    )

    g = build_graph([fr_main, fr_utils])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert u == "main.py::run:1"
    assert v == "pkg/utils.py::help:1"
    assert d["confidence"] == "high_confidence"
    assert d["provenance"] == "graph_builder:imported_call_resolution"


def test_python_alias_imported_call_resolution():
    """Verify resolution of aliased imports (e.g. from pkg.utils import help as helper)."""
    utils_fn = FunctionNode(id="pkg/utils.py::help:1", name="help", file="pkg/utils.py", start_line=1, end_line=5)
    fr_utils = FileParseResult(file="pkg/utils.py", functions=[utils_fn], classes=[], imports=[])

    main_fn = FunctionNode(id="main.py::run:1", name="run", file="main.py", start_line=1, end_line=10, calls=["helper"])
    fr_main = FileParseResult(
        file="main.py",
        functions=[main_fn],
        classes=[],
        imports=[ImportEdge(file="main.py", imported="pkg.utils.help", alias="helper", line=1)]
    )

    g = build_graph([fr_main, fr_utils])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert u == "main.py::run:1"
    assert v == "pkg/utils.py::help:1"
    assert d["confidence"] == "high_confidence"


def test_module_qualified_call_resolution():
    """Verify module-qualified calls (e.g. utils.help())."""
    utils_fn = FunctionNode(id="utils.py::help:1", name="help", file="utils.py", start_line=1, end_line=5)
    fr_utils = FileParseResult(file="utils.py", functions=[utils_fn], classes=[], imports=[])

    main_fn = FunctionNode(id="main.py::run:1", name="run", file="main.py", start_line=1, end_line=10, calls=["utils.help"])
    fr_main = FileParseResult(
        file="main.py",
        functions=[main_fn],
        classes=[],
        imports=[ImportEdge(file="main.py", imported="utils", alias=None, line=1)]
    )

    g = build_graph([fr_main, fr_utils])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert u == "main.py::run:1"
    assert v == "utils.py::help:1"
    assert d["confidence"] == "high_confidence"
    assert d["provenance"] == "graph_builder:module_qualified_resolution"


def test_class_method_receiver_and_inheritance_resolution():
    """Verify self.method() and super.method() resolution within class & inheritance chain."""
    cls_base = ClassNode(id="app.py::Base", name="Base", file="app.py", start_line=1, end_line=10, bases=[])
    fn_base = FunctionNode(id="app.py::Base.super_work", name="super_work", file="app.py", start_line=2, end_line=5, class_owner="Base")

    cls_child = ClassNode(id="app.py::Child", name="Child", file="app.py", start_line=11, end_line=25, bases=["Base"])
    fn_child_self = FunctionNode(id="app.py::Child.local_work", name="local_work", file="app.py", start_line=12, end_line=15, class_owner="Child")
    fn_child_caller = FunctionNode(
        id="app.py::Child.test",
        name="test",
        file="app.py",
        start_line=16,
        end_line=24,
        class_owner="Child",
        calls=["self.local_work", "super.super_work"]
    )

    fr = FileParseResult(file="app.py", functions=[fn_base, fn_child_self, fn_child_caller], classes=[cls_base, cls_child], imports=[])
    g = build_graph([fr])

    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls" and u == "app.py::Child.test"]
    assert len(call_edges) == 2

    targets = {v: d["provenance"] for _, v, d in call_edges}
    assert "app.py::Child.local_work" in targets
    assert targets["app.py::Child.local_work"] == "graph_builder:class_receiver_resolution"
    assert "app.py::Base.super_work" in targets
    assert targets["app.py::Base.super_work"] == "graph_builder:inheritance_receiver_resolution"


def test_java_constructor_new_call_resolution():
    """Verify Java/JS/TS 'new ClassName' call resolution."""
    cls_service = ClassNode(id="Service.java::Service", name="Service", file="Service.java", start_line=1, end_line=20, bases=[])
    fr_service = FileParseResult(file="Service.java", functions=[], classes=[cls_service], imports=[])

    app_fn = FunctionNode(id="App.java::main", name="main", file="App.java", start_line=1, end_line=10, calls=["new Service"])
    fr_app = FileParseResult(
        file="App.java",
        functions=[app_fn],
        classes=[],
        imports=[ImportEdge(file="App.java", imported="Service", alias=None, line=1)]
    )

    g = build_graph([fr_app, fr_service])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert v == "Service.java::Service"
    assert d["confidence"] == "high_confidence"


def test_jsts_relative_import_call_resolution():
    """Verify JavaScript/TypeScript relative import call resolution."""
    client_fn = FunctionNode(id="src/client.ts::render", name="render", file="src/client.ts", start_line=1, end_line=10)
    fr_client = FileParseResult(file="src/client.ts", functions=[client_fn], classes=[], imports=[])

    index_fn = FunctionNode(id="src/index.ts::init", name="init", file="src/index.ts", start_line=1, end_line=8, calls=["render"])
    fr_index = FileParseResult(
        file="src/index.ts",
        functions=[index_fn],
        classes=[],
        imports=[ImportEdge(file="src/index.ts", imported="./client", alias=None, line=1)]
    )

    g = build_graph([fr_index, fr_client])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    u, v, d = call_edges[0]
    assert v == "src/client.ts::render"
    assert d["confidence"] == "high_confidence"


def test_ambiguous_call_when_multiple_repo_candidates():
    """Verify ambiguity is preserved when multiple candidates exist without import evidence."""
    fn1 = FunctionNode(id="a.py::compute", name="compute", file="a.py", start_line=1, end_line=5)
    fn2 = FunctionNode(id="b.py::compute", name="compute", file="b.py", start_line=1, end_line=5)
    caller = FunctionNode(id="main.py::run", name="run", file="main.py", start_line=1, end_line=5, calls=["compute"])

    fr1 = FileParseResult(file="a.py", functions=[fn1], classes=[], imports=[])
    fr2 = FileParseResult(file="b.py", functions=[fn2], classes=[], imports=[])
    fr_main = FileParseResult(file="main.py", functions=[caller], classes=[], imports=[])

    g = build_graph([fr1, fr2, fr_main])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    _, v, d = call_edges[0]
    assert v == "ambiguous_call::compute"
    assert d["confidence"] == "flagged"
    assert d["reason"] == "2_candidate_definitions"


def test_unresolved_call_handling():
    """Verify unresolved calls are explicitly flagged with reason."""
    caller = FunctionNode(id="app.py::run", name="run", file="app.py", start_line=1, end_line=5, calls=["nonexistent_func"])
    fr = FileParseResult(file="app.py", functions=[caller], classes=[], imports=[])

    g = build_graph([fr])
    call_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "calls"]

    assert len(call_edges) == 1
    _, v, d = call_edges[0]
    assert v == "unresolved_call::nonexistent_func"
    assert d["confidence"] == "flagged"
    assert d["reason"] == "no_matching_definition_found"


def test_deterministic_call_resolution_output():
    """Verify deterministic graph serialization across multiple runs."""
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
        with open(os.path.join(d, "utils.py"), "w") as f:
            f.write("def help(): pass\n")
        with open(os.path.join(d, "main.py"), "w") as f:
            f.write("import utils\ndef run():\n    utils.help()\n")

        res1 = run_pipeline(None, d, None, c1)
        res2 = run_pipeline(None, d, None, c2)

        res1_clean = {k: v for k, v in res1.items() if k != "analyzed_at_utc"}
        res2_clean = {k: v for k, v in res2.items() if k != "analyzed_at_utc"}

        assert json.dumps(res1_clean, sort_keys=True, indent=2) == json.dumps(res2_clean, sort_keys=True, indent=2)
