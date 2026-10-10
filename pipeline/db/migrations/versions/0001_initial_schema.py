"""
Initial schema: all 10 tables for the repository analysis persistence layer.

Revision ID: 0001
Revises: None
Create Date: 2026-09-19

Tables created:
  repositories, snapshots, analysis_runs, analyzer_results,
  file_records, entity_records, graph_nodes, graph_edges,
  findings, health_scores
"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("repo_url", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_repositories_repo_url", "repositories", ["repo_url"])

    op.create_table(
        "snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("repository_id", sa.String(36), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.String(256), nullable=False),
        sa.Column("commit_sha", sa.String(256), nullable=True),
        sa.Column("cache_key_basis", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repository_id", "snapshot_id", name="uq_snapshot_repo_snapshot"),
    )
    op.create_index("ix_snapshots_repo_id", "snapshots", ["repository_id"])
    op.create_index("ix_snapshots_snapshot_id", "snapshots", ["snapshot_id"])

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("cache_schema_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("analyzer_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("languages", sa.Text(), nullable=True),
        sa.Column("files_analyzed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_errors_json", sa.Text(), nullable=True),
        sa.Column("analysis_status", sa.String(32), nullable=True),
        sa.Column("analyzed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_runs_snapshot_id", "analysis_runs", ["snapshot_id"])
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.create_index("ix_analysis_runs_analyzed_at", "analysis_runs", ["analyzed_at_utc"])

    op.create_table(
        "analyzer_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analyzer_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=True),
        sa.Column("errors_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "analyzer_name", name="uq_analyzer_result_run_name"),
    )
    op.create_index("ix_analyzer_results_run_id", "analyzer_results", ["run_id"])

    op.create_table(
        "file_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "file_path", name="uq_file_record_run_path"),
    )
    op.create_index("ix_file_records_run_id", "file_records", ["run_id"])
    op.create_index("ix_file_records_file_path", "file_records", ["file_path"])

    op.create_table(
        "entity_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("file_record_id", sa.String(36), sa.ForeignKey("file_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("class_owner", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("extra_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_entity_records_file_record_id", "entity_records", ["file_record_id"])
    op.create_index("ix_entity_records_entity_type", "entity_records", ["entity_type"])
    op.create_index("ix_entity_records_name", "entity_records", ["name"])
    op.create_index("ix_entity_records_node_id", "entity_records", ["node_id"])

    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("attributes_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "node_id", name="uq_graph_node_run_node"),
    )
    op.create_index("ix_graph_nodes_run_id", "graph_nodes", ["run_id"])
    op.create_index("ix_graph_nodes_node_type", "graph_nodes", ["node_type"])
    op.create_index("ix_graph_nodes_node_id", "graph_nodes", ["node_id"])

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("relation", sa.String(64), nullable=False),
        sa.Column("confidence", sa.String(64), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("attributes_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_graph_edges_run_id", "graph_edges", ["run_id"])
    op.create_index("ix_graph_edges_relation", "graph_edges", ["relation"])
    op.create_index("ix_graph_edges_source", "graph_edges", ["source"])
    op.create_index("ix_graph_edges_target", "graph_edges", ["target"])
    op.create_index("ix_graph_edges_confidence", "graph_edges", ["confidence"])

    op.create_table(
        "findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analyzer", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(256), nullable=True),
        sa.Column("severity", sa.String(32), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_findings_run_id", "findings", ["run_id"])
    op.create_index("ix_findings_analyzer", "findings", ["analyzer"])
    op.create_index("ix_findings_severity", "findings", ["severity"])
    op.create_index("ix_findings_file_path", "findings", ["file_path"])
    op.create_index("ix_findings_rule_id", "findings", ["rule_id"])

    op.create_table(
        "health_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("composite_health_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sub_scores_json", sa.Text(), nullable=True),
        sa.Column("component_statuses_json", sa.Text(), nullable=True),
        sa.Column("weights_used_json", sa.Text(), nullable=True),
        sa.Column("weights_renormalized", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("missing_components_json", sa.Text(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=True),
        sa.Column("scope_policy", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_health_score_run"),
    )
    op.create_index("ix_health_scores_run_id", "health_scores", ["run_id"])
    op.create_index("ix_health_scores_status", "health_scores", ["status"])


def downgrade() -> None:
    op.drop_table("health_scores")
    op.drop_table("findings")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("entity_records")
    op.drop_table("file_records")
    op.drop_table("analyzer_results")
    op.drop_table("analysis_runs")
    op.drop_table("snapshots")
    op.drop_table("repositories")
