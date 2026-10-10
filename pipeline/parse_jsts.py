"""
Structural parser for JavaScript (.js, .jsx) and TypeScript (.ts, .tsx) source files using tree-sitter.

Extracts classes, interfaces, functions, methods, arrow functions, inheritance, imports, and call sites.
No repository code is ever executed or built.
"""
from __future__ import annotations
import os
from typing import Dict, List, Optional, Tuple

try:
    from tree_sitter_languages import get_parser
    JS_PARSER = get_parser("javascript")
    TS_PARSER = get_parser("typescript")
    TSX_PARSER = get_parser("tsx")
except Exception:  # noqa: BLE001
    JS_PARSER = None
    TS_PARSER = None
    TSX_PARSER = None

from parse_python import FunctionNode, ClassNode, ImportEdge, FileParseResult


def get_parser_for_ext(ext: str):
    ext_l = ext.lower()
    if ext_l in (".js", ".jsx"):
        return JS_PARSER, "tree-sitter-javascript:AST-walk"
    elif ext_l == ".ts":
        return TS_PARSER, "tree-sitter-typescript:AST-walk"
    elif ext_l == ".tsx":
        return TSX_PARSER, "tree-sitter-tsx:AST-walk"
    return None, ""


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _extract_string_literal(node, source: bytes) -> Optional[str]:
    """Extract string content without quotes from string node or string fragment."""
    raw = _text(node, source)
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")) or (raw.startswith("`") and raw.endswith("`")):
        return raw[1:-1]
    return raw


def _extract_calls(body_node, source: bytes) -> List[str]:
    """Extract raw function and method calls inside a body node."""
    calls: List[str] = []
    if not body_node:
        return calls

    stack = [body_node]
    while stack:
        n = stack.pop()
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node:
                fn_text = _text(fn_node, source)
                if fn_text != "require":
                    calls.append(fn_text)
        elif n.type == "new_expression":
            constructor_node = n.child_by_field_name("constructor")
            if constructor_node:
                calls.append(f"new {_text(constructor_node, source)}")
        stack.extend(n.children)
    return calls


def parse_js_ts_file(filepath: str, repo_root: str) -> FileParseResult:
    rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
    _, ext = os.path.splitext(filepath)

    parser, provenance = get_parser_for_ext(ext)
    if parser is None:
        return FileParseResult(rel_path, [], [], [], parse_error=f"tree-sitter parser unavailable for extension '{ext}'")

    try:
        with open(filepath, "rb") as fh:
            source = fh.read()
    except OSError as e:
        return FileParseResult(rel_path, [], [], [], parse_error=str(e))

    if not source.strip():
        # Empty JS/TS file is valid syntax with no extracted entities
        return FileParseResult(rel_path, [], [], [])

    try:
        tree = parser.parse(source)
    except Exception as exc:  # noqa: BLE001
        return FileParseResult(rel_path, [], [], [], parse_error=f"JS/TS parse exception: {exc}")

    root = tree.root_node
    if root is None:
        return FileParseResult(rel_path, [], [], [], parse_error="Malformed JS/TS syntax: root AST node failed")

    functions: List[FunctionNode] = []
    classes: List[ClassNode] = []
    imports: List[ImportEdge] = []

    def walk(node, class_ctx: Optional[str] = None):
        # 1. Class and Interface declarations
        if node.type in ("class_declaration", "class", "interface_declaration", "ERROR"):
            is_class_like = node.type in ("class_declaration", "class", "interface_declaration")
            if not is_class_like:
                # For ERROR nodes, check if it contains a 'class' or 'interface' keyword child
                has_kw = any(c.type in ("class", "interface") for c in node.children)
                if not has_kw:
                    for c in node.children:
                        walk(c, class_ctx)
                    return

            name_node = node.child_by_field_name("name")
            if not name_node:
                for c in node.children:
                    if c.type in ("identifier", "type_identifier"):
                        name_node = c
                        break
            name = _text(name_node, source) if name_node else "<anonymous>"
            cname = f"{class_ctx}.{name}" if class_ctx else name

            bases: List[str] = []
            for child in node.children:
                if child.type in ("class_heritage", "extends_clause", "extends_type_clause", "implements_clause"):
                    for hc in child.children:
                        if hc.type in ("identifier", "type_identifier", "nested_identifier", "generic_type"):
                            bases.append(_text(hc, source))
                        elif hc.type in ("extends_clause", "implements_clause", "extends_type_clause"):
                            for tc in hc.children:
                                if tc.type in ("identifier", "type_identifier", "nested_identifier", "generic_type"):
                                    bases.append(_text(tc, source))

            cid = f"{rel_path}::{cname}:{node.start_point[0] + 1}"
            classes.append(ClassNode(
                id=cid,
                name=cname,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                bases=bases,
                provenance=provenance,
            ))

            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    walk(child, cname)
            return

        # 2. Method definitions inside classes / interfaces
        if node.type in ("method_definition", "abstract_method_signature", "method_signature"):
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anonymous>"
            body_node = node.child_by_field_name("body")
            calls = _extract_calls(body_node, source) if body_node else []

            fid = f"{rel_path}::{class_ctx + '.' if class_ctx else ''}{name}:{node.start_point[0] + 1}"
            functions.append(FunctionNode(
                id=fid,
                name=name,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                class_owner=class_ctx,
                calls=calls,
                provenance=provenance,
            ))
            return

        # 3. Function declarations & Generators
        if node.type in ("function_declaration", "generator_function_declaration"):
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anonymous>"
            body_node = node.child_by_field_name("body")
            calls = _extract_calls(body_node, source) if body_node else []

            fid = f"{rel_path}::{class_ctx + '.' if class_ctx else ''}{name}:{node.start_point[0] + 1}"
            functions.append(FunctionNode(
                id=fid,
                name=name,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                class_owner=class_ctx,
                calls=calls,
                provenance=provenance,
            ))

            if body_node:
                for child in body_node.children:
                    walk(child, class_ctx)
            return

        # 4. Variable declarations assigning arrow functions or function expressions
        if node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            val_node = node.child_by_field_name("value")
            if name_node and val_node and val_node.type in ("arrow_function", "function_expression", "generator_function"):
                name = _text(name_node, source)
                body_node = val_node.child_by_field_name("body")
                calls = _extract_calls(body_node, source) if body_node else []

                fid = f"{rel_path}::{class_ctx + '.' if class_ctx else ''}{name}:{node.start_point[0] + 1}"
                functions.append(FunctionNode(
                    id=fid,
                    name=name,
                    file=rel_path,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    class_owner=class_ctx,
                    calls=calls,
                    provenance=provenance,
                ))

                if body_node:
                    for child in body_node.children:
                        walk(child, class_ctx)
                return

            if val_node and val_node.type == "call_expression":
                fn_node = val_node.child_by_field_name("function")
                if fn_node and _text(fn_node, source) == "require":
                    args_node = val_node.child_by_field_name("arguments")
                    if args_node and args_node.children:
                        for arg in args_node.children:
                            if arg.type in ("string", "string_fragment"):
                                mod_name = _extract_string_literal(arg, source)
                                if mod_name:
                                    imports.append(ImportEdge(
                                        file=rel_path,
                                        imported=mod_name,
                                        alias=_text(name_node, source) if name_node else None,
                                        line=node.start_point[0] + 1,
                                        provenance=provenance,
                                    ))

        # 5. ES Import statements
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node:
                mod_name = _extract_string_literal(source_node, source)
                if mod_name:
                    imports.append(ImportEdge(
                        file=rel_path,
                        imported=mod_name,
                        alias=None,
                        line=node.start_point[0] + 1,
                        provenance=provenance,
                    ))
            return

        # 6. Re-export statements with from: export { foo } from 'bar'
        if node.type == "export_statement":
            source_node = node.child_by_field_name("source")
            if source_node:
                mod_name = _extract_string_literal(source_node, source)
                if mod_name:
                    imports.append(ImportEdge(
                        file=rel_path,
                        imported=mod_name,
                        alias=None,
                        line=node.start_point[0] + 1,
                        provenance=provenance,
                    ))
            declaration_node = node.child_by_field_name("declaration")
            if declaration_node:
                walk(declaration_node, class_ctx)
                return

        # 7. Standalone CommonJS require: require('mod')
        if node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node and _text(fn_node, source) == "require":
                args_node = node.child_by_field_name("arguments")
                if args_node and args_node.children:
                    for arg in args_node.children:
                        if arg.type in ("string", "string_fragment"):
                            mod_name = _extract_string_literal(arg, source)
                            if mod_name:
                                imports.append(ImportEdge(
                                    file=rel_path,
                                    imported=mod_name,
                                    alias=None,
                                    line=node.start_point[0] + 1,
                                    provenance=provenance,
                                ))

        for c in node.children:
            walk(c, class_ctx)

    walk(root)
    return FileParseResult(rel_path, functions, classes, imports)
