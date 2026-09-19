"""
Generic Parser Interface & Registry for Multilingual AST Analysis.

Provides a common contract (BaseParser), standard parse result models,
and a centralized ParserRegistry so that graph_builder and main pipeline
orchestration depend on language-agnostic parsing interfaces.

Extension Guide for S9 (Java) and S10 (JavaScript/TypeScript):
1. Subclass `BaseParser` (e.g. `JavaParser`, `JSParser`).
2. Implement `is_available()` to verify tree-sitter or parser dependencies.
3. Implement `parse_file(filepath, repo_root)` returning `FileParseResult`.
4. Register the new parser instance via `GLOBAL_PARSER_REGISTRY.register(NewParser())`.
"""
from __future__ import annotations
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# Re-export / import core parse result data models
from parse_python import (
    FunctionNode,
    ClassNode,
    ImportEdge,
    FileParseResult,
    PROVENANCE as PYTHON_PROVENANCE,
)


class BaseParser(ABC):
    """
    Abstract contract that all language parsers must implement.

    Subclasses (e.g., PythonParser, JavaParser, JSParser) specify:
    - name: Parser name (e.g. "tree-sitter-python")
    - version: Parser version tag or method (e.g. "AST-walk")
    - supported_languages: Set of normalized language names (e.g. {"python"})
    - supported_extensions: Set of file extensions including leading dot (e.g. {".py"})
    """

    def __init__(
        self,
        name: str,
        version: str,
        supported_languages: Set[str],
        supported_extensions: Set[str],
    ) -> None:
        self.name = name
        self.version = version
        self.supported_languages = {lang.lower() for lang in supported_languages}
        self.supported_extensions = {ext.lower() for ext in supported_extensions}

    @property
    def provenance_tag(self) -> str:
        return f"{self.name}:{self.version}"

    def is_available(self) -> Tuple[bool, Optional[str]]:
        """Returns (is_available, error_message_if_unavailable)."""
        return True, None

    def supports_extension(self, ext: str) -> bool:
        return ext.lower() in self.supported_extensions

    def supports_language(self, language: str) -> bool:
        return language.lower() in self.supported_languages

    @abstractmethod
    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        """Parses source file at filepath relative to repo_root into FileParseResult."""
        pass


class PythonParser(BaseParser):
    """Adapter wrapping tree-sitter Python parser behind BaseParser contract."""

    def __init__(self) -> None:
        super().__init__(
            name="tree-sitter-python",
            version="AST-walk",
            supported_languages={"python"},
            supported_extensions={".py"},
        )

    def is_available(self) -> Tuple[bool, Optional[str]]:
        try:
            from parse_python import PARSER
            if PARSER is not None:
                return True, None
            return False, "Python tree-sitter parser is not initialized"
        except Exception as exc:  # noqa: BLE001
            return False, f"Failed to load tree-sitter-python: {exc}"

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        from parse_python import parse_file as python_parse_file
        return python_parse_file(filepath, repo_root)


class JavaParser(BaseParser):
    """Adapter wrapping tree-sitter Java parser behind BaseParser contract."""

    def __init__(self) -> None:
        super().__init__(
            name="tree-sitter-java",
            version="AST-walk",
            supported_languages={"java"},
            supported_extensions={".java"},
        )

    def is_available(self) -> Tuple[bool, Optional[str]]:
        try:
            from parse_java import PARSER
            if PARSER is not None:
                return True, None
            return False, "Java tree-sitter parser is not initialized"
        except Exception as exc:  # noqa: BLE001
            return False, f"Failed to load tree-sitter-java: {exc}"

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        from parse_java import parse_java_file
        return parse_java_file(filepath, repo_root)


class JavaScriptParser(BaseParser):
    """Adapter wrapping tree-sitter JavaScript parser behind BaseParser contract."""

    def __init__(self) -> None:
        super().__init__(
            name="tree-sitter-javascript",
            version="AST-walk",
            supported_languages={"javascript"},
            supported_extensions={".js", ".jsx"},
        )

    def is_available(self) -> Tuple[bool, Optional[str]]:
        try:
            from parse_jsts import JS_PARSER
            if JS_PARSER is not None:
                return True, None
            return False, "JavaScript tree-sitter parser is not initialized"
        except Exception as exc:  # noqa: BLE001
            return False, f"Failed to load tree-sitter-javascript: {exc}"

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        from parse_jsts import parse_js_ts_file
        return parse_js_ts_file(filepath, repo_root)


class TypeScriptParser(BaseParser):
    """Adapter wrapping tree-sitter TypeScript parser behind BaseParser contract."""

    def __init__(self) -> None:
        super().__init__(
            name="tree-sitter-typescript",
            version="AST-walk",
            supported_languages={"typescript"},
            supported_extensions={".ts", ".tsx"},
        )

    def is_available(self) -> Tuple[bool, Optional[str]]:
        try:
            from parse_jsts import TS_PARSER, TSX_PARSER
            if TS_PARSER is not None and TSX_PARSER is not None:
                return True, None
            return False, "TypeScript/TSX tree-sitter parser is not initialized"
        except Exception as exc:  # noqa: BLE001
            return False, f"Failed to load tree-sitter-typescript: {exc}"

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        from parse_jsts import parse_js_ts_file
        return parse_js_ts_file(filepath, repo_root)


class ParserRegistry:
    """
    Centralized registry of language parsers.
    Orchestrates file parsing across multiple languages in a repository.
    """

    def __init__(self) -> None:
        self._parsers: List[BaseParser] = []
        self._ext_map: Dict[str, BaseParser] = {}

    def register(self, parser: BaseParser) -> None:
        """Registers a BaseParser instance for its supported file extensions."""
        self._parsers.append(parser)
        for ext in parser.supported_extensions:
            self._ext_map[ext.lower()] = parser

    def get_parser_for_file(self, filepath: str) -> Optional[BaseParser]:
        """Returns the registered BaseParser matching the file extension, or None."""
        _, ext = os.path.splitext(filepath)
        return self._ext_map.get(ext.lower())

    def supports_file(self, filepath: str) -> bool:
        """Checks if any registered parser supports the given file extension."""
        return self.get_parser_for_file(filepath) is not None

    def parse_file(self, filepath: str, repo_root: str) -> FileParseResult:
        """
        Parses a single file using the appropriate registered parser.
        Returns explicit parse_error if unsupported or unavailable.
        """
        rel_path = os.path.relpath(filepath, repo_root).replace("\\", "/")
        parser = self.get_parser_for_file(filepath)

        if parser is None:
            _, ext = os.path.splitext(filepath)
            return FileParseResult(
                file=rel_path,
                functions=[],
                classes=[],
                imports=[],
                parse_error=f"Unsupported file extension '{ext}' for file {rel_path}",
            )

        avail, err = parser.is_available()
        if not avail:
            return FileParseResult(
                file=rel_path,
                functions=[],
                classes=[],
                imports=[],
                parse_error=f"Parser '{parser.name}' is unavailable: {err}",
            )

        return parser.parse_file(filepath, repo_root)

    def parse_repository(self, repo_root: str) -> List[FileParseResult]:
        """Walk repo_root and parse all supported source files in deterministic order."""
        SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", "site-packages", "dist", "build"}
        results: List[FileParseResult] = []

        for dirpath, dirnames, filenames in os.walk(repo_root):
            dirnames[:] = sorted([d for d in dirnames if d not in SKIP_DIRS])
            for fn in sorted(filenames):
                full_path = os.path.join(dirpath, fn)
                if self.supports_file(full_path):
                    results.append(self.parse_file(full_path, repo_root))

        results.sort(key=lambda r: r.file)
        return results


# Global singleton parser registry
GLOBAL_PARSER_REGISTRY = ParserRegistry()
GLOBAL_PARSER_REGISTRY.register(PythonParser())
GLOBAL_PARSER_REGISTRY.register(JavaParser())
GLOBAL_PARSER_REGISTRY.register(JavaScriptParser())
GLOBAL_PARSER_REGISTRY.register(TypeScriptParser())


def parse_repository(repo_root: str) -> List[FileParseResult]:
    """Convenience function delegating repository parsing to GLOBAL_PARSER_REGISTRY."""
    return GLOBAL_PARSER_REGISTRY.parse_repository(repo_root)


def parse_file(filepath: str, repo_root: str) -> FileParseResult:
    """Convenience function delegating single file parsing to GLOBAL_PARSER_REGISTRY."""
    return GLOBAL_PARSER_REGISTRY.parse_file(filepath, repo_root)

