import os
import pytest
from pipeline.parser_interface import (
    GLOBAL_PARSER_REGISTRY,
    BaseParser,
    JavaScriptParser,
    TypeScriptParser,
    parse_file,
    parse_repository,
)
from pipeline.parse_jsts import parse_js_ts_file
from pipeline.graph_builder import build_graph, graph_summary

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "jsts_repo")


class TestJsTsParserContract:
    def test_js_parser_attributes(self):
        parser = JavaScriptParser()
        assert parser.name == "tree-sitter-javascript"
        assert parser.version == "AST-walk"
        assert parser.provenance_tag == "tree-sitter-javascript:AST-walk"
        assert parser.supports_extension(".js")
        assert parser.supports_extension(".jsx")
        assert parser.supports_language("javascript")

    def test_ts_parser_attributes(self):
        parser = TypeScriptParser()
        assert parser.name == "tree-sitter-typescript"
        assert parser.version == "AST-walk"
        assert parser.provenance_tag == "tree-sitter-typescript:AST-walk"
        assert parser.supports_extension(".ts")
        assert parser.supports_extension(".tsx")
        assert parser.supports_language("typescript")

    def test_parsers_available(self):
        js_parser = JavaScriptParser()
        ts_parser = TypeScriptParser()
        avail_js, err_js = js_parser.is_available()
        avail_ts, err_ts = ts_parser.is_available()
        assert avail_js is True, f"JS parser unavailable: {err_js}"
        assert avail_ts is True, f"TS parser unavailable: {err_ts}"

    def test_parsers_registered_in_global_registry(self):
        js_parser = GLOBAL_PARSER_REGISTRY.get_parser_for_file("app.js")
        jsx_parser = GLOBAL_PARSER_REGISTRY.get_parser_for_file("component.jsx")
        ts_parser = GLOBAL_PARSER_REGISTRY.get_parser_for_file("service.ts")
        tsx_parser = GLOBAL_PARSER_REGISTRY.get_parser_for_file("widget.tsx")

        assert js_parser is not None
        assert js_parser.name == "tree-sitter-javascript"
        assert jsx_parser is not None
        assert jsx_parser.name == "tree-sitter-javascript"

        assert ts_parser is not None
        assert ts_parser.name == "tree-sitter-typescript"
        assert tsx_parser is not None
        assert tsx_parser.name == "tree-sitter-typescript"


class TestJsTsExtraction:
    def test_js_app_fixture_extraction(self):
        app_file = os.path.join(FIXTURE_DIR, "app.js")
        res = parse_file(app_file, FIXTURE_DIR)
        assert res.parse_error is None
        assert res.file == "app.js"

        class_names = [c.name for c in res.classes]
        assert "BaseController" in class_names
        assert "UserController" in class_names

        user_ctrl = next(c for c in res.classes if c.name == "UserController")
        assert "BaseController" in user_ctrl.bases

        func_names = [f.name for f in res.functions]
        assert "log" in func_names
        assert "getUser" in func_names
        assert "createServer" in func_names
        assert "arrowHandler" in func_names

        imports = [i.imported for i in res.imports]
        assert "./utils" in imports
        assert "express" in imports

    def test_jsx_component_fixture_extraction(self):
        jsx_file = os.path.join(FIXTURE_DIR, "component.jsx")
        res = parse_file(jsx_file, FIXTURE_DIR)
        assert res.parse_error is None
        assert res.file == "component.jsx"

        func_names = [f.name for f in res.functions]
        assert "Button" in func_names
        assert "render" in func_names

        class_names = [c.name for c in res.classes]
        assert "Card" in class_names

    def test_ts_service_fixture_extraction(self):
        ts_file = os.path.join(FIXTURE_DIR, "service.ts")
        res = parse_file(ts_file, FIXTURE_DIR)
        assert res.parse_error is None
        assert res.file == "service.ts"

        class_names = [c.name for c in res.classes]
        assert "Identifiable" in class_names
        assert "UserService" in class_names
        assert "UserServiceImpl" in class_names

        user_service = next(c for c in res.classes if c.name == "UserService")
        assert "Identifiable" in user_service.bases

        user_service_impl = next(c for c in res.classes if c.name == "UserServiceImpl")
        assert "UserService" in user_service_impl.bases

        func_names = [f.name for f in res.functions]
        assert "getId" in func_names
        assert "getUser" in func_names
        assert "formatUser" in func_names

        imports = [i.imported for i in res.imports]
        assert "./types" in imports

    def test_tsx_widget_fixture_extraction(self):
        tsx_file = os.path.join(FIXTURE_DIR, "widget.tsx")
        res = parse_file(tsx_file, FIXTURE_DIR)
        assert res.parse_error is None
        assert res.file == "widget.tsx"

        func_names = [f.name for f in res.functions]
        assert "UserWidget" in func_names

        class_names = [c.name for c in res.classes]
        assert "WidgetProps" in class_names

        imports = [i.imported for i in res.imports]
        assert "react" in imports
        assert "./types" in imports

    def test_empty_js_file_handling(self):
        empty_file = os.path.join(FIXTURE_DIR, "empty.js")
        res = parse_file(empty_file, FIXTURE_DIR)
        assert res.parse_error is None
        assert len(res.functions) == 0
        assert len(res.classes) == 0
        assert len(res.imports) == 0

    def test_malformed_js_syntax_handling(self):
        malformed_file = os.path.join(FIXTURE_DIR, "malformed.js")
        res = parse_file(malformed_file, FIXTURE_DIR)
        assert res.parse_error is None
        class_names = [c.name for c in res.classes]
        assert "MalformedClass" in class_names

    def test_jsts_graph_generation(self):
        parse_results = parse_repository(FIXTURE_DIR)
        g = build_graph(parse_results)
        summary = graph_summary(g)

        assert summary["total_nodes"] > 0
        assert summary["total_edges"] > 0

        # Verify contains edges for JS/TS classes/functions
        contains_edges = [e for _, _, e in g.edges(data=True) if e.get("relation") == "contains"]
        assert len(contains_edges) > 0
