"""0003_source_chunks

Revision ID: 0003_source_chunks
Revises: 0002_jobs_and_stages
Create Date: 2026-10-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'source_chunks',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=36), nullable=False),
        sa.Column('chunk_id', sa.String(length=64), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('language', sa.String(length=32), nullable=True),
        sa.Column('entity_name', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(length=32), nullable=True),
        sa.Column('provenance', sa.Text(), nullable=True),
        sa.Column('chunk_hash', sa.String(length=64), nullable=False),
        sa.Column('commit_sha', sa.String(length=256), nullable=True),
        sa.Column('chunker_version', sa.String(length=32), nullable=False, server_default='1'),
        sa.Column('schema_version', sa.String(length=32), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['analysis_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'chunk_id', name='uq_source_chunk_run_chunk_id')
    )
    op.create_index(op.f('ix_source_chunks_run_id'), 'source_chunks', ['run_id'], unique=False)
    op.create_index(op.f('ix_source_chunks_chunk_id'), 'source_chunks', ['chunk_id'], unique=False)
    op.create_index(op.f('ix_source_chunks_file_path'), 'source_chunks', ['file_path'], unique=False)
    op.create_index(op.f('ix_source_chunks_start_line'), 'source_chunks', ['start_line'], unique=False)
    op.create_index(op.f('ix_source_chunks_chunk_hash'), 'source_chunks', ['chunk_hash'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_source_chunks_chunk_hash'), table_name='source_chunks')
    op.drop_index(op.f('ix_source_chunks_start_line'), table_name='source_chunks')
    op.drop_index(op.f('ix_source_chunks_file_path'), table_name='source_chunks')
    op.drop_index(op.f('ix_source_chunks_chunk_id'), table_name='source_chunks')
    op.drop_index(op.f('ix_source_chunks_run_id'), table_name='source_chunks')
    op.drop_table('source_chunks')
