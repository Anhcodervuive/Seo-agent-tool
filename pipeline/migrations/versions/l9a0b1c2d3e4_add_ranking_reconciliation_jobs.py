"""Add durable background collection jobs for Standard ranking tasks.

Revision ID: l9a0b1c2d3e4
Revises: k8f9a0b1c2d3
"""

import sqlalchemy as sa
from alembic import op


revision = "l9a0b1c2d3e4"
down_revision = "k8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ranking_reconciliation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("next_poll_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["snapshots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("snapshot_id"),
    )
    op.create_index("ix_ranking_reconciliation_jobs_client_id", "ranking_reconciliation_jobs", ["client_id"])
    op.create_index("ix_ranking_reconciliation_jobs_snapshot_id", "ranking_reconciliation_jobs", ["snapshot_id"], unique=True)
    op.create_index("ix_ranking_reconciliation_jobs_status", "ranking_reconciliation_jobs", ["status"])
    op.create_index("ix_ranking_reconciliation_jobs_next_poll_at", "ranking_reconciliation_jobs", ["next_poll_at"])
    op.create_index(
        "ix_ranking_reconciliation_jobs_status_next_poll",
        "ranking_reconciliation_jobs",
        ["status", "next_poll_at"],
    )
    op.create_index("ix_ranking_reconciliation_jobs_updated_at", "ranking_reconciliation_jobs", ["updated_at"])


def downgrade():
    op.drop_table("ranking_reconciliation_jobs")
