"""Persist analysis configuration fingerprints and force-refresh job intent.

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "config_fingerprint" not in _columns("analysis_runs"):
        op.add_column("analysis_runs", sa.Column("config_fingerprint", sa.String(64), nullable=True))
    if "force_refresh" not in _columns("analysis_jobs"):
        op.add_column(
            "analysis_jobs",
            sa.Column("force_refresh", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "force_refresh" in _columns("analysis_jobs"):
        with op.batch_alter_table("analysis_jobs") as batch:
            batch.drop_column("force_refresh")
    if "config_fingerprint" in _columns("analysis_runs"):
        with op.batch_alter_table("analysis_runs") as batch:
            batch.drop_column("config_fingerprint")
