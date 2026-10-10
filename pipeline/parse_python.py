"""
Structural parser for Python files using tree-sitter.

Every fact extracted here (functions, classes, imports, line ranges) comes
directly from a syntactic AST walk -- it is a deterministic, reproducible
fact, never an LLM guess. Each extracted item carries a `provenance` tag
naming the exact tool that produced it, per the project's evidence-linking
requirement.

Confidence levels used throughout the pipeline:
  "certain"   -> derived directly and unambiguously from the AST
  "heuristic" -> derived by best-effort name/string matching, may be wrong
  "flagged"   -> pattern detected but NOT resolved (e.g. dynamic call);
                 surfaced to the user rather than silently guessed
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional
from tree_sitter_languages import get_parser

PARSER = get_parser("python")
PROVENANCE = "tree-sitter-python:AST-walk"


@dataclass
class FunctionNode:
    id: str
    name: str
    file: str
    start_line: int
    end_line: int
    class_owner: Optional[str] = None
    calls: list = field(default_factory=list)  # raw call-name strings (unresolved)
    provenance: str = PROVENANCE


@dataclass
class ClassNode:
    id: str
    name: str
    file: str
    start_line: int
    end_line: int
    bases: list = field(default_factory=list)
    provenance: str = PROVENANCE


@dataclass
class ImportEdge:
    file: str
    imported: str          # dotted module path as written
    alias: Optional[str]
    line: int
    provenance: str = PROVENANCE


@dataclass
class FileParseResult:
    file: str
    functions: list
    classes: list
    imports: list
    parse_error: Optional[str] = None


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _dotted_name(node, source: bytes) -> str:
    """Reconstruct a dotted_name / attribute chain into 'a.b.c' form."""
    return _text(node, source).replace(" ", "")


def _extract_calls(func_body_node, source: bytes) -> list:
    """
    Best-effort extraction of call *names* inside a function body.
    This does NOT resolve which function definition a call points to --
    that resolution happens later in graph_builder.py and is explicitly
    confidence-tagged. Here we only record the raw textual call target.
    """
    calls = []
    stack = [func_body_node]
    while stack:
        node = stack.pop()
        if node.type == "call":
            fn_part = node.child_by_field_name("function")
            if fn_part is not None:
                calls.append(_text(fn_part, source))
        stack.extend(node.children)
    return calls


def parse_file(filepath: str, repo_root: str) -> FileParseResult:
    rel_path = os.path.relpath(filepath, repo_root)
    try:
        with open(filepath, "rb") as fh:
            source = fh.read()
    except OSError as e:
        return FileParseResult(rel_path, [], [], [], parse_error=str(e))

    tree = PARSER.parse(source)
    root = tree.root_node

    functions, classes, imports = [], [], []

    def walk(node, class_ctx: Optional[str] = None):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            body_node = node.child_by_field_name("body")
            name = _text(name_node, source) if name_node else "<anonymous>"
            fid = f"{rel_path}::{class_ctx + '.' if class_ctx else ''}{name}:{node.start_point[0]+1}"
            functions.append(FunctionNode(
                id=fid,
                name=name,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                class_owner=class_ctx,
                calls=_extract_calls(body_node, source) if body_node else [],
            ))
            # do not descend further for nested-function double counting avoidance
            for child in node.children:
                if child.type == "block":
                    for sub in child.children:
                        walk(sub, class_ctx)
            return

        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anonymous>"
            bases = []
            superclasses = node.child_by_field_name("superclasses")
            if superclasses:
                bases = [
                    _text(c, source) for c in superclasses.children
                    if c.type in ("identifier", "attribute")
                ]
            cid = f"{rel_path}::{name}:{node.start_point[0]+1}"
            classes.append(ClassNode(
                id=cid,
                name=name,
                file=rel_path,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                bases=bases,
            ))
            for child in node.children:
                walk(child, name)
            return

        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(ImportEdge(rel_path, _dotted_name(child, source), None, node.start_point[0] + 1))
                elif child.type == "aliased_import":
                    dotted = child.child_by_field_name("name")
                    alias = child.child_by_field_name("alias")
                    imports.append(ImportEdge(
                        rel_path,
                        _dotted_name(dotted, source) if dotted else "?",
                        _text(alias, source) if alias else None,
                        node.start_point[0] + 1,
                    ))

        if node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = _dotted_name(module_node, source) if module_node else "."
            for child in node.children:
                if child.type == "dotted_name" and child != module_node:
                    imports.append(ImportEdge(rel_path, f"{module}.{_dotted_name(child, source)}", None, node.start_point[0] + 1))
                elif child.type == "aliased_import":
                    dotted = child.child_by_field_name("name")
                    alias = child.child_by_field_name("alias")
                    name = _dotted_name(dotted, source) if dotted else "?"
                    imports.append(ImportEdge(rel_path, f"{module}.{name}", _text(alias, source) if alias else None, node.start_point[0] + 1))
                elif child.type == "wildcard_import":
                    imports.append(ImportEdge(rel_path, f"{module}.*", None, node.start_point[0] + 1))

        for child in node.children:
            walk(child, class_ctx)

    walk(root)
    return FileParseResult(rel_path, functions, classes, imports)


def parse_repository(repo_root: str) -> list:
    """Walk repo_root, parse every .py file, skip common noise directories."""
    SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", "site-packages", "dist", "build"}
    results = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                results.append(parse_file(os.path.join(dirpath, fn), repo_root))
    return results
