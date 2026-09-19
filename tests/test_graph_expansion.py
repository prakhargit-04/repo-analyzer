"""
Unit and integration tests for Session 11: Knowledge Graph Expansion.
Verifies multilingual graph building, inheritance relations, module dependencies,
static analysis findings, confidence semantics, determinism, and backwards compatibility.
"""
import os
import tempfile
import pytest
from pipeline.parser_interface import parse_repository, FileParseResult, ClassNode, FunctionNode, ImportEdge
from pipeline.graph_builder import build_graph, graph_summary
from pipeline.main import run_pipeline


def test_inherits_relationship_resolution_same_file():
    """Verify class inheritance resolution within the same file (structural_certain)."""
    fr = FileParseResult(
        file="app.py",
        functions=[],
        classes=[
            ClassNode(id="app.py::BaseService", name="BaseService", file="app.py", start_line=1, end_line=10, bases=[]),
            ClassNode(id="app.py::UserService", name="UserService", file="app.py", start_line=11, end_line=25, bases=["BaseService"]),
        ],
        imports=[]
    )
    g = build_graph([fr])

    assert g.has_node("app.py::UserService")
    assert g.has_node("app.py::BaseService")

    inherits_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "inherits"]
    assert len(inherits_edges) == 1
    u, v, d = inherits_edges[0]
    assert u == "app.py::UserService"
    assert v == "app.py::BaseService"
    assert d["confidence"] == "structural_certain"
    assert d["base_name"] == "BaseService"


def test_inherits_relationship_resolution_cross_file():
    """Verify class inheritance resolution across files (low_confidence)."""
    fr1 = FileParseResult(
        file="base.py",
        functions=[],
        classes=[ClassNode(id="base.py::BaseModel", name="BaseModel", file="base.py", start_line=1, end_line=5, bases=[])],
        imports=[]
    )
    fr2 = FileParseResult(
        file="models/user.py",
        functions=[],
        classes=[ClassNode(id="models/user.py::User", name="User", file="models/user.py", start_line=1, end_line=10, bases=["BaseModel"])],
        imports=[]
    )
    g = build_graph([fr1, fr2])

    inherits_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "inherits"]
    assert len(inherits_edges) == 1
    u, v, d = inherits_edges[0]
    assert u == "models/user.py::User"
    assert v == "base.py::BaseModel"
    assert d["confidence"] == "low_confidence"


def test_inherits_relationship_external_target():
    """Verify unresolved/external base class creates class_target node."""
    fr = FileParseResult(
        file="schema.py",
        functions=[],
        classes=[ClassNode(id="schema.py::UserSchema", name="UserSchema", file="schema.py", start_line=1, end_line=5, bases=["pydantic.BaseModel"])],
        imports=[]
    )
    g = build_graph([fr])

    target_id = "class_target::pydantic.BaseModel"
    assert g.has_node(target_id)
    assert g.nodes[target_id]["type"] == "class_target"
    assert g.nodes[target_id]["provenance"] == "external/unresolved"

    inherits_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "inherits"]
    assert len(inherits_edges) == 1
    assert inherits_edges[0][1] == target_id


def test_module_depends_on_relationship():
    """Verify file-to-file module dependency edges generation."""
    fr1 = FileParseResult(
        file="main.py",
        functions=[],
        classes=[],
        imports=[ImportEdge(file="main.py", imported="pkg.utils", alias=None, line=1)]
    )
    fr2 = FileParseResult(
        file="pkg/utils.py",
        functions=[],
        classes=[],
        imports=[]
    )
    g = build_graph([fr1, fr2])

    depends_edges = [(u, v, d) for u, v, d in g.edges(data=True) if d.get("relation") == "depends_on"]
    assert len(depends_edges) == 1
    u, v, d = depends_edges[0]
    assert u == "main.py"
    assert v == "pkg/utils.py"
    assert d["imported_module"] == "pkg.utils"
    assert d["confidence"] in ("structural_certain", "high_confidence")


def test_static_analysis_finding_nodes_and_edges():
    """Verify static analysis findings create finding nodes and link to file/function."""
    fr = FileParseResult(
        file="app.py",
        functions=[FunctionNode(id="app.py::process_data", name="process_data", file="app.py", start_line=5, end_line=15)],
        classes=[],
        imports=[]
    )
    static_analysis = {
        "security": {
            "status": "success",
            "results": [
                {
                    "filename": "app.py",
                    "line_number": 10,
                    "test_id": "B101",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Use of assert detected"
                }
            ]
        },
        "semgrep_findings": {
            "status": "success",
            "results": [
                {
                    "file": "app.py",
                    "line": 8,
                    "rule_id": "python.lang.security.audit.eval",
                    "severity": "HIGH",
                    "message": "Dynamic code execution"
                }
            ]
        }
    }

    g = build_graph([fr], static_analysis=static_analysis)
    summary = graph_summary(g)

    assert summary["finding_nodes_total"] == 2
    assert summary["has_finding_edges_total"] >= 2

    finding_nodes = [n for n, d in g.nodes(data=True) if d.get("type") == "finding"]
    assert len(finding_nodes) == 2

    # Check function-level finding link
    func_finding_edges = [
        (u, v, d) for u, v, d in g.edges(data=True)
        if d.get("relation") == "has_finding" and u == "app.py::process_data"
    ]
    assert len(func_finding_edges) == 2


def test_multilingual_graph_building():
    """Verify combined graph building across Python, Java, JS, TS files."""
    fr_py = FileParseResult(
        file="src/server.py",
        functions=[FunctionNode(id="src/server.py::run", name="run", file="src/server.py", start_line=1, end_line=10)],
        classes=[],
        imports=[]
    )
    fr_java = FileParseResult(
        file="src/App.java",
        functions=[FunctionNode(id="src/App.java::main", name="main", file="src/App.java", start_line=1, end_line=5)],
        classes=[ClassNode(id="src/App.java::App", name="App", file="src/App.java", start_line=1, end_line=5, bases=[])],
        imports=[]
    )
    fr_js = FileParseResult(
        file="src/client.js",
        functions=[FunctionNode(id="src/client.js::render", name="render", file="src/client.js", start_line=1, end_line=8)],
        classes=[],
        imports=[]
    )

    g = build_graph([fr_py, fr_java, fr_js])
    summary = graph_summary(g)

    assert g.has_node("src/server.py")
    assert g.has_node("src/App.java")
    assert g.has_node("src/client.js")
    assert summary["total_nodes"] >= 6


def test_graph_summary_expansion_backwards_compatibility():
    """Verify graph_summary returns all classic fields plus expanded summary fields."""
    fr = FileParseResult(file="a.py", functions=[], classes=[], imports=[])
    g = build_graph([fr])
    summary = graph_summary(g)

    # Classic keys required by canonical schema
    assert "total_nodes" in summary
    assert "total_edges" in summary
    assert "call_edges_total" in summary
    assert "call_edges_by_confidence" in summary
    assert "call_edges_resolved_pct" in summary
    assert "resolution_caveat" in summary

    # Expanded keys introduced in S11
    assert "inherits_edges_total" in summary
    assert "depends_on_edges_total" in summary
    assert "has_finding_edges_total" in summary
    assert "finding_nodes_total" in summary


def test_deterministic_expanded_graph_serialization():
    """Verify byte-for-byte serialization determinism of expanded graph."""
    with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as c1, tempfile.TemporaryDirectory() as c2:
        with open(os.path.join(d, "Base.py"), "w") as f:
            f.write("class Base:\n    pass\n")
        with open(os.path.join(d, "Child.py"), "w") as f:
            f.write("import Base\nclass Child(Base.Base):\n    def work(self):\n        pass\n")

        res1 = run_pipeline(None, d, None, c1)
        res2 = run_pipeline(None, d, None, c2)

        res1_clean = {k: v for k, v in res1.items() if k != "analyzed_at_utc"}
        res2_clean = {k: v for k, v in res2.items() if k != "analyzed_at_utc"}

        import json
        assert json.dumps(res1_clean, sort_keys=True, indent=2) == json.dumps(res2_clean, sort_keys=True, indent=2)
