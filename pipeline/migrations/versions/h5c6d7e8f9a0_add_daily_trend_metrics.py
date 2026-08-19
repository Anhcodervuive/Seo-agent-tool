"""Add daily GA4 and GSC aggregates for accurate trend charts.

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
"""

import sqlalchemy as sa
from alembic import op


revision = "h5c6d7e8f9a0"
down_revision = "g4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ga4_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("sessions", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_users", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("client_id", "metric_date", name="uq_ga4_daily_metrics_client_date"),
    )
    op.create_index("ix_ga4_daily_metrics_client_id", "ga4_daily_metrics", ["client_id"])
    op.create_index("ix_ga4_daily_metrics_metric_date", "ga4_daily_metrics", ["metric_date"])
    op.create_index("ix_ga4_daily_metrics_source_snapshot_id", "ga4_daily_metrics", ["source_snapshot_id"])
    op.create_index("ix_ga4_daily_metrics_client_date", "ga4_daily_metrics", ["client_id", "metric_date"])

    op.create_table(
        "gsc_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ctr", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_position", sa.Float(), nullable=True),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("client_id", "metric_date", name="uq_gsc_daily_metrics_client_date"),
    )
    op.create_index("ix_gsc_daily_metrics_client_id", "gsc_daily_metrics", ["client_id"])
    op.create_index("ix_gsc_daily_metrics_metric_date", "gsc_daily_metrics", ["metric_date"])
    op.create_index("ix_gsc_daily_metrics_source_snapshot_id", "gsc_daily_metrics", ["source_snapshot_id"])
    op.create_index("ix_gsc_daily_metrics_client_date", "gsc_daily_metrics", ["client_id", "metric_date"])


def downgrade():
    op.drop_table("gsc_daily_metrics")
    op.drop_table("ga4_daily_metrics")
