"""Add a cursor pagination index for Copilot messages.

Revision ID: k8f9a0b1c2d3
Revises: j7e8f9a0b1c2
"""

from alembic import op


revision = "k8f9a0b1c2d3"
down_revision = "j7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_copilot_messages_conversation_id_id",
        "copilot_messages",
        ["conversation_id", "id"],
    )


def downgrade():
    op.drop_index("ix_copilot_messages_conversation_id_id", table_name="copilot_messages")
