"""
SQLAlchemy ORM models for the repository analysis persistence layer.

Design principles:
  1. Canonical analysis JSON is the *external/API* representation.
     These models are the *storage* representation. Field names mirror the
     canonical schema where possible, but the schema is normalized.
  2. Stable identifiers:
     - repositories.id  : UUID, repo_url is the natural key (unique constraint)
     - snapshots.id     : UUID, (repository_id, snapshot_id) is the natural key
     - analysis_runs.id : UUID, start time + snapshot gives full lineage
  3. Repeated analyses of the same repo+snapshot produce a new analysis_run
     without corrupting previous runs (idempotent upsert at repo/snapshot level).
  4. Partial/failed runs are first-class: analysis_runs.status can be
     "pending" | "complete" | "partial" | "failed".
  5. All version strings (schema_version, analyzer_version, cache_schema_version)
     are stored on analysis_runs for full provenance.
  6. pgvector / embeddings: NOT in this schema (S14 scope excludes them).

Index strategy:
  - Single-column indexes: declared with mapped_column(index=True) only.
    Do NOT also declare them in __table_args__ -- that would create two indexes
    with different names and fail on SQLite.
  - Multi-column unique constraints: declared in __table_args__.

Table hierarchy:
  repositories
    └── snapshots
          └── analysis_runs
                ├── analyzer_results
                ├── file_records
                │     └── entity_records
                ├── graph_nodes
                ├── graph_edges
                ├── findings
                └── health_scores
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------

class Repository(Base):
    """One row per unique repository URL or local path."""
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    repo_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc, onupdate=_now_utc
    )

    snapshots: Mapped[List["Snapshot"]] = relationship(
        "Snapshot", back_populates="repository", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# snapshots
# ---------------------------------------------------------------------------

class Snapshot(Base):
    """
    One row per unique (repository, snapshot_id) pair.
    snapshot_id is the git SHA for clones, content hash for local paths.
    """
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("repository_id", "snapshot_id", name="uq_snapshot_repo_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # commit_sha is the raw git SHA (may differ from snapshot_id for local paths)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    cache_key_basis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    repository: Mapped["Repository"] = relationship("Repository", back_populates="snapshots")
    analysis_runs: Mapped[List["AnalysisRun"]] = relationship(
        "AnalysisRun", back_populates="snapshot", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# analysis_runs
# ---------------------------------------------------------------------------

class AnalysisRun(Base):
    """
    One row per pipeline execution.
    Multiple runs can exist for the same snapshot (re-analysis, schema version bump, etc.).
    status: "pending" | "complete" | "partial" | "failed"
    """
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    # Version provenance stored with every run
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    cache_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    analyzer_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # Languages detected in this run
    languages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array as text
    files_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_errors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    analysis_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    analyzed_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="analysis_runs")
    analyzer_results: Mapped[List["AnalyzerResult"]] = relationship(
        "AnalyzerResult", back_populates="run", cascade="all, delete-orphan"
    )
    file_records: Mapped[List["FileRecord"]] = relationship(
        "FileRecord", back_populates="run", cascade="all, delete-orphan"
    )
    graph_nodes: Mapped[List["GraphNode"]] = relationship(
        "GraphNode", back_populates="run", cascade="all, delete-orphan"
    )
    graph_edges: Mapped[List["GraphEdge"]] = relationship(
        "GraphEdge", back_populates="run", cascade="all, delete-orphan"
    )
    findings: Mapped[List["Finding"]] = relationship(
        "Finding", back_populates="run", cascade="all, delete-orphan"
    )
    health_score: Mapped[Optional["HealthScore"]] = relationship(
        "HealthScore", back_populates="run", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# analyzer_results
# ---------------------------------------------------------------------------

class AnalyzerResult(Base):
    """
    One row per tool (radon_cc, radon_mi, bandit, semgrep, gitleaks, osv, lizard, ...)
    per analysis run. Stores the full normalized tool output as JSON.
    """
    __tablename__ = "analyzer_results"
    __table_args__ = (
        UniqueConstraint("run_id", "analyzer_name", name="uq_analyzer_result_run_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    analyzer_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Serialized list of result dicts (full tool output)
    results_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    errors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="analyzer_results")


# ---------------------------------------------------------------------------
# file_records
# ---------------------------------------------------------------------------

class FileRecord(Base):
    """One row per source file per analysis run."""
    __tablename__ = "file_records"
    __table_args__ = (
        UniqueConstraint("run_id", "file_path", name="uq_file_record_run_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="file_records")
    entities: Mapped[List["EntityRecord"]] = relationship(
        "EntityRecord", back_populates="file_record", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# entity_records
# ---------------------------------------------------------------------------

class EntityRecord(Base):
    """
    One row per parsed entity (function, class, import) per file per run.
    entity_type: "function" | "class" | "import"
    """
    __tablename__ = "entity_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    file_record_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("file_records.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # node_id matches knowledge_graph node IDs for join
    node_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    class_owner: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # bases, aliases, etc.

    file_record: Mapped["FileRecord"] = relationship("FileRecord", back_populates="entities")


# ---------------------------------------------------------------------------
# graph_nodes
# ---------------------------------------------------------------------------

class GraphNode(Base):
    """
    Denormalized graph node for efficient graph queries.
    node_id matches the knowledge_graph JSON 'id' field.
    """
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", name="uq_graph_node_run_node"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="graph_nodes")


# ---------------------------------------------------------------------------
# graph_edges
# ---------------------------------------------------------------------------

class GraphEdge(Base):
    """
    Denormalized graph edge for efficient graph queries.
    source/target match node_id values in graph_nodes.
    """
    __tablename__ = "graph_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    target: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    relation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="graph_edges")


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------

class Finding(Base):
    """
    One row per static analysis finding (bandit issue, semgrep hit, gitleaks secret, osv vuln).
    Analyzer-normalized; mirrors the graph finding nodes.
    """
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    analyzer: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    severity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provenance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="findings")


# ---------------------------------------------------------------------------
# health_scores
# ---------------------------------------------------------------------------

class HealthScore(Base):
    """
    One row per analysis run. Stores composite + per-component scores.
    sub_scores_json / component_statuses_json / weights_used_json are JSON objects.
    """
    __tablename__ = "health_scores"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_health_score_run"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    composite_health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sub_scores_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    component_statuses_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weights_used_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    weights_renormalized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    missing_components_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_policy: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    run: Mapped["AnalysisRun"] = relationship("AnalysisRun", back_populates="health_score")
