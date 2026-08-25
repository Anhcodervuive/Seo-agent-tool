"""Add user-controlled business-fit labels to keyword research.

Revision ID: n1b2c3d4e5f6
Revises: m0a1b2c3d4e5
"""

import sqlalchemy as sa
from alembic import op


revision = "n1b2c3d4e5f6"
down_revision = "m0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("keyword_research_runs", sa.Column("relevance_settings", sa.JSON(), nullable=True))
    op.add_column("keyword_research_results", sa.Column("business_fit", sa.String(length=16), nullable=True))
    op.add_column("keyword_research_results", sa.Column("business_matches", sa.JSON(), nullable=True))
    op.create_index(
        "ix_keyword_research_results_run_type_fit_rank",
        "keyword_research_results",
        ["run_id", "result_type", "business_fit", "source_rank", "id"],
    )


def downgrade():
    op.drop_index("ix_keyword_research_results_run_type_fit_rank", table_name="keyword_research_results")
    op.drop_column("keyword_research_results", "business_matches")
    op.drop_column("keyword_research_results", "business_fit")
    op.drop_column("keyword_research_runs", "relevance_settings")
