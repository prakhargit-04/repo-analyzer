"""
Structural parser for Java source files using tree-sitter.

Extracts classes, methods, constructors, inheritance/interfaces, imports, and calls
deterministically from Java AST walks. No repository code is ever compiled or executed.
"""
from __future__ import annotations
import os
from typing import List, Optional

try:
    from tree_sitter_languages import get_parser
    PARSER = get_parser("java")
except Exception:  # noqa: BLE001
    PARSER = None

PROVENANCE = "tree-sitter-java:AST-walk"

from parse_python import FunctionNode, ClassNode, ImportEdge, FileParseResult


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def _extract_calls(body_node, source: bytes) -> List[str]:
    """Extract raw method call target strings inside a method body."""
    calls: List[str] = []
    stack = [body_node]
    while stack:
        n = stack.pop()
        if n.type == "method_invocation":
            name_n = n.child_by_field_name("name")
            obj_n = n.child_by_field_name("object")
            if obj_n and name_n:
                calls.append(f"{_text(obj_n, source)}.{_text(name_n, source)}")
            elif name_n:
                calls.append(_text(name_n, source))
        elif n.type == "object_creation_expression":
            type_n = n.child_by_field_name("type")
            if type_n:
                calls.append(f"new {_text(type_n, source)}")
        stack.extend(n.children)
    return calls


def parse_java_file(filepath: str, repo_root: str) -> FileParseResult:
    rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
    if PARSER is None:
        return FileParseResult(rel_path, [], [], [], parse_error="tree-sitter Java parser is unavailable")

    try:
        with open(filepath, "rb") as fh:
            source = fh.read()
    except OSError as e:
        return FileParseResult(rel_path, [], [], [], parse_error=str(e))

    if not source.strip():
        # Empty Java file is valid syntax with no extracted entities
        return FileParseResult(rel_path, [], [], [])

    try:
        tree = PARSER.parse(source)
    except Exception as exc:  # noqa: BLE001
        return FileParseResult(rel_path, [], [], [], parse_error=f"Java parse exception: {exc}")

    root = tree.root_node
    if root is None:
        return FileParseResult(rel_path, [], [], [], parse_error="Malformed Java syntax: root AST node failed")

    functions: List[FunctionNode] = []
    classes: List[ClassNode] = []
    imports: List[ImportEdge] = []

    def walk(node, class_ctx: Optional[str] = None):
        if node.type in ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration"):
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anonymous>"
            cname = f"{class_ctx}.{name}" if class_ctx else name

            bases: List[str] = []
            sc = node.child_by_field_name("superclass")
            if sc:
                sc_text = _text(sc, source)
                if sc_text.startswith("extends "):
                    sc_text = sc_text[len("extends "):].strip()
                if sc_text:
                    bases.append(sc_text)

            ifaces = node.child_by_field_name("interfaces")
            if ifaces:
                for child in ifaces.children:
                    if child.type == "type_list":
                        for t in child.children:
                            if t.type == "type_identifier":
                                bases.append(_text(t, source))
                    elif child.type == "type_identifier":
                        bases.append(_text(child, source))

            cid = f"{rel_path}::{cname}:{node.start_point[0] + 1}"
            classes.append(ClassNode(
                id=cid,
                name=cname,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                bases=bases,
                provenance=PROVENANCE,
            ))

            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    walk(child, cname)
            return

        if node.type in ("method_declaration", "constructor_declaration"):
            if node.type == "constructor_declaration":
                name = class_ctx.split(".")[-1] if class_ctx else "<init>"
            else:
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
                provenance=PROVENANCE,
            ))
            return

        if node.type == "import_declaration":
            imp_text = ""
            for c in node.children:
                if c.type in ("scoped_identifier", "identifier"):
                    imp_text = _text(c, source)
                    break
            if imp_text:
                imports.append(ImportEdge(
                    file=rel_path,
                    imported=imp_text,
                    alias=None,
                    line=node.start_point[0] + 1,
                    provenance=PROVENANCE,
                ))
            return

        for c in node.children:
            walk(c, class_ctx)

    walk(root)
    return FileParseResult(rel_path, functions, classes, imports)
