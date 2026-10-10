"""0004_source_embeddings

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'source_embeddings',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('source_chunk_id', sa.String(length=64), nullable=False),
        sa.Column('chunk_id', sa.String(length=64), nullable=False),
        sa.Column('repo_url', sa.Text(), nullable=False),
        sa.Column('commit_sha', sa.String(length=256), nullable=True),
        sa.Column('model_name', sa.String(length=64), nullable=False),
        sa.Column('model_version', sa.String(length=32), nullable=False),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('pipeline_version', sa.String(length=32), nullable=False, server_default='1'),
        sa.Column('vector_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_chunk_id'], ['source_chunks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'source_chunk_id', 'model_name', 'model_version', name='uq_source_embedding_chunk_model')
    )
    op.create_index(op.f('ix_source_embeddings_run_id'), 'source_embeddings', ['run_id'], unique=False)
    op.create_index(op.f('ix_source_embeddings_source_chunk_id'), 'source_embeddings', ['source_chunk_id'], unique=False)
    op.create_index(op.f('ix_source_embeddings_chunk_id'), 'source_embeddings', ['chunk_id'], unique=False)
    op.create_index(op.f('ix_source_embeddings_repo_url'), 'source_embeddings', ['repo_url'], unique=False)
    op.create_index(op.f('ix_source_embeddings_commit_sha'), 'source_embeddings', ['commit_sha'], unique=False)
    op.create_index(op.f('ix_source_embeddings_model_name'), 'source_embeddings', ['model_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_source_embeddings_model_name'), table_name='source_embeddings')
    op.drop_index(op.f('ix_source_embeddings_commit_sha'), table_name='source_embeddings')
    op.drop_index(op.f('ix_source_embeddings_repo_url'), table_name='source_embeddings')
    op.drop_index(op.f('ix_source_embeddings_chunk_id'), table_name='source_embeddings')
    op.drop_index(op.f('ix_source_embeddings_source_chunk_id'), table_name='source_embeddings')
    op.drop_index(op.f('ix_source_embeddings_run_id'), table_name='source_embeddings')
    op.drop_table('source_embeddings')
