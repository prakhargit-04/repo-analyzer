"""0007_health_formula_version

Record which scoring rules produced a health score (health_score.HEALTH_FORMULA_VERSION)
so scores from different formula versions are never compared as if equivalent.
Nullable: rows written before this migration have no version and none is invented.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    insp = sa.inspect(op.get_bind())
    return "formula_version" in {c["name"] for c in insp.get_columns("health_scores")}


def upgrade() -> None:
    # Idempotent: a database bootstrapped by create_all() may already have it.
    if not _has_column():
        op.add_column("health_scores", sa.Column("formula_version", sa.String(16), nullable=True))


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("health_scores") as batch_op:
            batch_op.drop_column("formula_version")
