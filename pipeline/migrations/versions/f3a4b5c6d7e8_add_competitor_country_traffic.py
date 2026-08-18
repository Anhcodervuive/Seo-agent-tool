"""Add country-wise competitor traffic tracking.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

import sqlalchemy as sa
from alembic import op


revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("competitor_traffic_locations", sa.JSON(), nullable=True))
    op.create_table(
        "competitor_country_traffic",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location", sa.String(length=64), nullable=False),
        sa.Column("estimated_organic_traffic", sa.Float(), nullable=True),
        sa.Column("organic_keyword_count", sa.Integer(), nullable=True),
        sa.Column("top_10_keyword_count", sa.Integer(), nullable=True),
        sa.Column("estimated_traffic_cost", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="complete"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("snapshot_id", "competitor_id", "location", name="uq_competitor_country_traffic_snapshot_market"),
    )
    op.create_index("ix_competitor_country_traffic_snapshot_id", "competitor_country_traffic", ["snapshot_id"])
    op.create_index("ix_competitor_country_traffic_competitor_id", "competitor_country_traffic", ["competitor_id"])
    op.create_index("ix_competitor_country_traffic_location", "competitor_country_traffic", ["location"])


def downgrade():
    op.drop_index("ix_competitor_country_traffic_location", table_name="competitor_country_traffic")
    op.drop_index("ix_competitor_country_traffic_competitor_id", table_name="competitor_country_traffic")
    op.drop_index("ix_competitor_country_traffic_snapshot_id", table_name="competitor_country_traffic")
    op.drop_table("competitor_country_traffic")
    op.drop_column("clients", "competitor_traffic_locations")
