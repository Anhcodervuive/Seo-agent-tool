"""Store the selected search-intent profile for one-page audits.

Revision ID: p3q4r5s6t7u8
Revises: o2c3d4e5f6a7
"""

import sqlalchemy as sa
from alembic import op


revision = "p3q4r5s6t7u8"
down_revision = "o2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("one_page_audits", sa.Column("intent_profile", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("one_page_audits", "intent_profile")
