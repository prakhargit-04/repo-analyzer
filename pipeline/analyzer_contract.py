"""
Common Analyzer Contract & Failure Semantics.

All static analysis components (Radon CC, Radon MI, Bandit, and future tools
like Lizard, Semgrep, Gitleaks, OSV, language-specific parsers) MUST implement
this contract.

Statuses:
  - "success"     : Tool completed cleanly and output is complete.
  - "partial"     : Tool ran but some files/blocks failed or were incomplete.
  - "failed"      : Tool crashed, timed out, missing executable, or returned
                    unparsable stdout/stderr.
  - "unsupported" : Language or file type is not supported by this analyzer.
  - "unavailable" : Tool is configured but binary/package is not installed or
                    disabled in the current environment.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AnalyzerStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


VALID_STATUS_VALUES = {s.value for s in AnalyzerStatus}


@dataclass
class AnalyzerResult:
    """Standard normalized result wrapper returned by all analyzers."""
    status: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    provenance: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.status, AnalyzerStatus):
            self.status = self.status.value
        if self.status not in VALID_STATUS_VALUES:
            raise ValueError(f"Invalid AnalyzerStatus: {self.status!r}. Must be one of {VALID_STATUS_VALUES}")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "status": self.status,
            "results": self.results,
        }
        if self.errors:
            d["errors"] = self.errors
        if self.provenance:
            d["provenance"] = self.provenance
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class BaseAnalyzer(ABC):
    """Abstract Base Class for repository analyzers."""

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    @property
    def provenance_tag(self) -> str:
        return f"{self.name}:{self.version}"

    @abstractmethod
    def is_available(self) -> tuple[bool, Optional[str]]:
        """Returns (is_available, error_message_if_not)."""
        pass

    @abstractmethod
    def supports_language(self, language: str) -> bool:
        """Returns True if this analyzer supports the given language."""
        pass

    @abstractmethod
    def analyze(self, repo_root: str, files: List[str]) -> AnalyzerResult:
        """Runs analysis over repo_root and return an AnalyzerResult."""
        pass
