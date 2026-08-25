"""Add persisted link-target validation details.

Revision ID: o2c3d4e5f6a7
Revises: n1b2c3d4e5f6
"""

import sqlalchemy as sa
from alembic import op


revision = "o2c3d4e5f6a7"
down_revision = "n1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("crawl_page_links", sa.Column("target_final_url", sa.Text(), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_status_source", sa.String(length=32), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_error_type", sa.String(length=64), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_error_message", sa.Text(), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_checked_at", sa.String(length=64), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_response_time_ms", sa.Integer(), nullable=True))
    op.add_column("crawl_page_links", sa.Column("target_redirect_count", sa.Integer(), nullable=True))
    op.create_index(
        "ix_crawl_page_links_snapshot_status",
        "crawl_page_links",
        ["snapshot_id", "target_status"],
    )


def downgrade():
    op.drop_index("ix_crawl_page_links_snapshot_status", table_name="crawl_page_links")
    op.drop_column("crawl_page_links", "target_redirect_count")
    op.drop_column("crawl_page_links", "target_response_time_ms")
    op.drop_column("crawl_page_links", "target_checked_at")
    op.drop_column("crawl_page_links", "target_error_message")
    op.drop_column("crawl_page_links", "target_error_type")
    op.drop_column("crawl_page_links", "target_status_source")
    op.drop_column("crawl_page_links", "target_final_url")
