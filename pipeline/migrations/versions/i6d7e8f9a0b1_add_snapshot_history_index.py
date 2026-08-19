"""Index project audit-history cursor queries.

Revision ID: i6d7e8f9a0b1
Revises: h5c6d7e8f9a0
"""

from alembic import op


revision = "i6d7e8f9a0b1"
down_revision = "h5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_snapshots_client_created_id",
        "snapshots",
        ["client_id", "created_at", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_snapshots_client_created_id", table_name="snapshots")
