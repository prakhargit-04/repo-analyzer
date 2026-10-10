"""0005_add_knowledge_graph_summary

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('analysis_runs', sa.Column('knowledge_graph_summary_json', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('analysis_runs', 'knowledge_graph_summary_json')
