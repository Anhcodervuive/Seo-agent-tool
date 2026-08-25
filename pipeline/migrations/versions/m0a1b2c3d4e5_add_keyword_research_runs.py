"""Add durable keyword research runs and results.

Revision ID: m0a1b2c3d4e5
Revises: l9a0b1c2d3e4
"""

import sqlalchemy as sa
from alembic import op


revision = "m0a1b2c3d4e5"
down_revision = "l9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "keyword_research_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("input_keywords", sa.JSON(), nullable=False),
        sa.Column("location", sa.String(length=96), nullable=False, server_default="United States"),
        sa.Column("language", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("provider_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_keyword_research_runs_client_id", "keyword_research_runs", ["client_id"])
    op.create_index("ix_keyword_research_runs_created_by_user_id", "keyword_research_runs", ["created_by_user_id"])
    op.create_index("ix_keyword_research_runs_status", "keyword_research_runs", ["status"])
    op.create_index("ix_keyword_research_runs_created_at", "keyword_research_runs", ["created_at"])
    op.create_index("ix_keyword_research_runs_updated_at", "keyword_research_runs", ["updated_at"])
    op.create_index(
        "ix_keyword_research_runs_status_created_id",
        "keyword_research_runs",
        ["status", "created_at", "id"],
    )

    op.create_table(
        "keyword_research_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("result_type", sa.String(length=24), nullable=False, server_default="keyword"),
        sa.Column("keyword", sa.String(length=700), nullable=False),
        sa.Column("source_types", sa.JSON(), nullable=False),
        sa.Column("source_rank", sa.Integer(), nullable=True),
        sa.Column("search_volume", sa.Integer(), nullable=True),
        sa.Column("keyword_difficulty", sa.Integer(), nullable=True),
        sa.Column("cpc", sa.Float(), nullable=True),
        sa.Column("competition", sa.Float(), nullable=True),
        sa.Column("search_intent", sa.String(length=64), nullable=True),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["keyword_research_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "result_type", "keyword", name="uq_keyword_research_result_run_type_keyword"),
    )
    op.create_index("ix_keyword_research_results_run_id", "keyword_research_results", ["run_id"])
    op.create_index("ix_keyword_research_results_result_type", "keyword_research_results", ["result_type"])
    op.create_index(
        "ix_keyword_research_results_run_type_rank",
        "keyword_research_results",
        ["run_id", "result_type", "source_rank", "id"],
    )


def downgrade():
    op.drop_table("keyword_research_results")
    op.drop_table("keyword_research_runs")
