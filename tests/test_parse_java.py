"""
Unit and contract tests for JavaParser and Java AST extraction (Session 9).
"""
from __future__ import annotations
import os
import tempfile
import pytest

from parse_java import parse_java_file, PROVENANCE as JAVA_PROVENANCE
from parser_interface import JavaParser, GLOBAL_PARSER_REGISTRY, parse_repository, parse_file
from parse_python import FileParseResult
from graph_builder import build_graph, graph_summary

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "java_repo")


class TestJavaParserContract:
    """Contract tests for JavaParser implementing BaseParser interface."""

    def test_java_parser_attributes(self):
        parser = JavaParser()
        assert parser.name == "tree-sitter-java"
        assert parser.version == "AST-walk"
        assert parser.provenance_tag == "tree-sitter-java:AST-walk"
        assert parser.supports_language("java") is True
        assert parser.supports_language("Java") is True  # case-insensitive
        assert parser.supports_extension(".java") is True
        assert parser.supports_extension(".JAVA") is True

    def test_java_parser_is_available(self):
        parser = JavaParser()
        avail, err = parser.is_available()
        assert avail is True
        assert err is None

    def test_java_parser_registered_in_global_registry(self):
        parser = GLOBAL_PARSER_REGISTRY.get_parser_for_file("Main.java")
        assert parser is not None
        assert isinstance(parser, JavaParser)


class TestJavaExtraction:
    """Entity extraction tests for Java source files."""

    def test_java_app_fixture_extraction(self):
        app_path = os.path.join(FIXTURES_DIR, "App.java")
        res = parse_file(app_path, FIXTURES_DIR)
        assert isinstance(res, FileParseResult)
        assert res.file == "App.java"
        assert res.parse_error is None

        # Check extracted classes
        class_names = [c.name for c in res.classes]
        assert "App" in class_names
        assert "App.InnerClass" in class_names

        app_cls = next(c for c in res.classes if c.name == "App")
        assert "BaseApp" in app_cls.bases
        assert "Runnable" in app_cls.bases
        assert app_cls.provenance == JAVA_PROVENANCE

        inner_cls = next(c for c in res.classes if c.name == "App.InnerClass")
        assert "BaseInner" in inner_cls.bases

        # Check extracted functions/methods/constructors
        fn_names = [f.name for f in res.functions]
        assert "App" in fn_names           # constructor
        assert "run" in fn_names           # method
        assert "innerMethod" in fn_names   # inner method

        run_fn = next(f for f in res.functions if f.name == "run")
        assert run_fn.class_owner == "App"
        assert "helper" in run_fn.calls
        assert "System.out.println" in run_fn.calls

        # Check extracted imports
        imported_targets = [imp.imported for imp in res.imports]
        assert "java.util.List" in imported_targets
        assert "java.lang.Math.max" in imported_targets

    def test_empty_java_file_handling(self):
        empty_path = os.path.join(FIXTURES_DIR, "Empty.java")
        res = parse_file(empty_path, FIXTURES_DIR)
        assert res.file == "Empty.java"
        assert res.parse_error is None
        assert res.functions == []
        assert res.classes == []
        assert res.imports == []

    def test_malformed_java_syntax_handling(self):
        malformed_path = os.path.join(FIXTURES_DIR, "Malformed.java")
        res = parse_file(malformed_path, FIXTURES_DIR)
        assert res.file == "Malformed.java"
        # tree-sitter recovers or records parse error gracefully without process crash
        assert isinstance(res.functions, list)

    def test_java_graph_generation(self):
        """Verify Knowledge Graph building from Java parse results."""
        parse_results = parse_repository(FIXTURES_DIR)
        g = build_graph(parse_results)

        assert g.has_node("App.java")
        summary = graph_summary(g)
        assert summary["total_nodes"] > 0
        assert summary["total_edges"] >= 0
