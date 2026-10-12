"""Add composite indexes used by paginated graph read paths."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _existing_indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade():
    gn_indexes = _existing_indexes("graph_nodes")
    ge_indexes = _existing_indexes("graph_edges")

    if "ix_graph_nodes_run_node_type" not in gn_indexes:
        op.create_index("ix_graph_nodes_run_node_type", "graph_nodes", ["run_id", "node_type"])
    if "ix_graph_nodes_run_file_path" not in gn_indexes:
        op.create_index("ix_graph_nodes_run_file_path", "graph_nodes", ["run_id", "file_path"])

    if "ix_graph_edges_run_source" not in ge_indexes:
        op.create_index("ix_graph_edges_run_source", "graph_edges", ["run_id", "source"])
    if "ix_graph_edges_run_target" not in ge_indexes:
        op.create_index("ix_graph_edges_run_target", "graph_edges", ["run_id", "target"])


def downgrade():
    gn_indexes = _existing_indexes("graph_nodes")
    ge_indexes = _existing_indexes("graph_edges")

    if "ix_graph_edges_run_target" in ge_indexes:
        op.drop_index("ix_graph_edges_run_target", table_name="graph_edges")
    if "ix_graph_edges_run_source" in ge_indexes:
        op.drop_index("ix_graph_edges_run_source", table_name="graph_edges")
    if "ix_graph_nodes_run_file_path" in gn_indexes:
        op.drop_index("ix_graph_nodes_run_file_path", table_name="graph_nodes")
    if "ix_graph_nodes_run_node_type" in gn_indexes:
        op.drop_index("ix_graph_nodes_run_node_type", table_name="graph_nodes")
