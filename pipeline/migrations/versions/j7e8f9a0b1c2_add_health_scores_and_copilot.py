"""Add persisted health-score history and durable Copilot chat runs.

Revision ID: j7e8f9a0b1c2
Revises: i6d7e8f9a0b1
"""

from alembic import op
import sqlalchemy as sa


revision = "j7e8f9a0b1c2"
down_revision = "i6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "health_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=32), nullable=False, server_default="No data"),
        sa.Column("tone", sa.String(length=16), nullable=False, server_default="neutral"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("algorithm_version", sa.String(length=32), nullable=False, server_default="v2"),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_health_scores_client_calculated", "health_scores", ["client_id", "calculated_at", "id"])

    op.create_table(
        "copilot_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_conversations_client_id", "copilot_conversations", ["client_id"])
    op.create_index("ix_copilot_conversations_created_by_user_id", "copilot_conversations", ["created_by_user_id"])
    op.create_index("ix_copilot_conversations_updated_at", "copilot_conversations", ["updated_at"])

    op.create_table(
        "copilot_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("copilot_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_messages_conversation_id", "copilot_messages", ["conversation_id"])
    op.create_index("ix_copilot_messages_created_at", "copilot_messages", ["created_at"])

    op.create_table(
        "copilot_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("copilot_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("copilot_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("model_name", sa.String(length=160), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("conversation_id", "client_id", "requested_by_user_id", "user_message_id", "status", "created_at"):
        op.create_index(f"ix_copilot_runs_{column}", "copilot_runs", [column])
    op.create_index("ix_copilot_runs_pending", "copilot_runs", ["status", "created_at", "id"])

    op.create_table(
        "copilot_tool_invocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("copilot_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result_meta", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_copilot_tool_invocations_run_id", "copilot_tool_invocations", ["run_id"])


def downgrade():
    op.drop_table("copilot_tool_invocations")
    op.drop_index("ix_copilot_runs_pending", table_name="copilot_runs")
    op.drop_table("copilot_runs")
    op.drop_table("copilot_messages")
    op.drop_table("copilot_conversations")
    op.drop_index("ix_health_scores_client_calculated", table_name="health_scores")
    op.drop_table("health_scores")
