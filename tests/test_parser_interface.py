"""
Unit tests for Session 8 Generic Parser Interface and ParserRegistry.
"""
from __future__ import annotations
import os
import tempfile
import pytest

from parser_interface import (
    BaseParser,
    PythonParser,
    ParserRegistry,
    GLOBAL_PARSER_REGISTRY,
    parse_repository,
    parse_file,
)
from parse_python import FileParseResult, FunctionNode, ClassNode, ImportEdge
from graph_builder import build_graph


class DummyCustomParser(BaseParser):
    """Dummy concrete parser for testing registry and contract methods."""

    def __init__(self, available: bool = True):
        super().__init__(
            name="dummy-parser",
            version="1.0.0",
            supported_languages={"dummy"},
            supported_extensions={".dum"},
        )
        self._available = available

    def is_available(self) -> tuple[bool, str | None]:
        if self._available:
            return True, None
        return False, "Dummy parser engine missing"

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
        return FileParseResult(
            file=rel_path,
            functions=[
                FunctionNode(
                    id=f"{rel_path}::dummy_func:1",
                    name="dummy_func",
                    file=rel_path,
                    start_line=1,
                    end_line=5,
                    provenance=self.provenance_tag,
                )
            ],
            classes=[],
            imports=[],
        )


def test_parser_interface_contract():
    """Verify BaseParser methods and provenance tag construction."""
    parser = DummyCustomParser(available=True)
    assert parser.name == "dummy-parser"
    assert parser.version == "1.0.0"
    assert parser.provenance_tag == "dummy-parser:1.0.0"
    assert parser.supports_language("dummy") is True
    assert parser.supports_language("DUMMY") is True  # case-insensitive
    assert parser.supports_extension(".dum") is True
    assert parser.supports_extension(".DUM") is True  # case-insensitive

    avail, err = parser.is_available()
    assert avail is True
    assert err is None


def test_python_parser_adapter():
    """Verify PythonParser adapter implements BaseParser contract and parses Python code."""
    parser = PythonParser()
    assert parser.name == "tree-sitter-python"
    assert parser.version == "AST-walk"
    assert parser.provenance_tag == "tree-sitter-python:AST-walk"
    assert parser.supports_language("python") is True
    assert parser.supports_extension(".py") is True

    avail, err = parser.is_available()
    assert avail is True
    assert err is None

    with tempfile.TemporaryDirectory() as d:
        sample_file = os.path.join(d, "sample.py")
        with open(sample_file, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 42\n")

        res = parser.parse_file(sample_file, d)
        assert isinstance(res, FileParseResult)
        assert res.file == "sample.py"
        assert len(res.functions) == 1
        assert res.functions[0].name == "foo"


def test_supported_extensions_languages():
    """Verify registry correctly resolves parsers for supported extensions."""
    registry = ParserRegistry()
    python_parser = PythonParser()
    dummy_parser = DummyCustomParser()

    registry.register(python_parser)
    registry.register(dummy_parser)

    assert registry.supports_file("main.py") is True
    assert registry.supports_file("script.PY") is True
    assert registry.supports_file("test.dum") is True
    assert registry.supports_file("index.html") is False

    assert registry.get_parser_for_file("main.py") == python_parser
    assert registry.get_parser_for_file("test.dum") == dummy_parser
    assert registry.get_parser_for_file("unknown.xyz") is None


def test_unsupported_language_behavior():
    """Unsupported file extension produces explicit parse_error, not silent success."""
    registry = ParserRegistry()
    registry.register(PythonParser())

    with tempfile.TemporaryDirectory() as d:
        unsupported_file = os.path.join(d, "config.ini")
        with open(unsupported_file, "w", encoding="utf-8") as f:
            f.write("[section]\nkey=val\n")

        res = registry.parse_file(unsupported_file, d)
        assert res.file == "config.ini"
        assert res.parse_error is not None
        assert "Unsupported file extension" in res.parse_error
        assert res.functions == []
        assert res.classes == []
        assert res.imports == []


def test_parser_unavailable_behavior():
    """Unavailable parser produces explicit parse_error."""
    registry = ParserRegistry()
    unavail_parser = DummyCustomParser(available=False)
    registry.register(unavail_parser)

    with tempfile.TemporaryDirectory() as d:
        dummy_file = os.path.join(d, "app.dum")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("dummy code\n")

        res = registry.parse_file(dummy_file, d)
        assert res.parse_error is not None
        assert "unavailable" in res.parse_error.lower()


def test_malformed_source_parse_errors():
    """Syntax error in source file is handled safely without crashing."""
    with tempfile.TemporaryDirectory() as d:
        bad_file = os.path.join(d, "bad.py")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("def (((( syntax error !!!\n")

        res = parse_file(bad_file, d)
        assert res.file == "bad.py"
        # tree-sitter parses error nodes gracefully or returns empty functions list
        assert isinstance(res.functions, list)


def test_deterministic_parser_output():
    """Repository parsing returns deterministically sorted file parse results."""
    with tempfile.TemporaryDirectory() as d:
        for fname in ("c.py", "a.py", "b.py"):
            with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
                f.write(f"# {fname}\ndef fn_{fname[0]}(): pass\n")

        registry = ParserRegistry()
        registry.register(PythonParser())

        res1 = registry.parse_repository(d)
        res2 = registry.parse_repository(d)

        files1 = [r.file for r in res1]
        files2 = [r.file for r in res2]

        assert files1 == ["a.py", "b.py", "c.py"]
        assert files1 == files2


def test_preservation_of_existing_python_entities():
    """Verify that Python entity extraction (functions, classes, bases, imports, calls) is preserved."""
    code = """import os
from sys import path as sys_path

class Base:
    pass

class Derived(Base):
    def method(self):
        os.path.join("a", "b")
"""
    with tempfile.TemporaryDirectory() as d:
        filepath = os.path.join(d, "app.py")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(code)

        res = parse_file(filepath, d)
        assert res.file == "app.py"
        assert len(res.classes) == 2
        assert len(res.functions) == 1
        assert len(res.imports) == 2

        derived = next(c for c in res.classes if c.name == "Derived")
        assert derived.bases == ["Base"]

        method = res.functions[0]
        assert method.name == "method"
        assert method.class_owner == "Derived"
        assert "os.path.join" in method.calls


def test_graph_generation_using_parser_abstraction():
    """Build NetworkX knowledge graph from ParserRegistry output."""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "main.py"), "w", encoding="utf-8") as f:
            f.write("import utils\n\ndef run():\n    utils.help()\n")
        with open(os.path.join(d, "utils.py"), "w", encoding="utf-8") as f:
            f.write("def help():\n    pass\n")

        parse_results = parse_repository(d)
        graph = build_graph(parse_results)

        assert graph.has_node("main.py")
        assert graph.has_node("utils.py")
        assert graph.number_of_nodes() >= 4
