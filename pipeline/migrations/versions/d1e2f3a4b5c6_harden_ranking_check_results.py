"""harden ranking check result context and status

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-17 10:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def _add_column_if_missing(table, column):
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def upgrade():
    _add_column_if_missing("rankings", sa.Column("language", sa.String(length=20), nullable=True))
    _add_column_if_missing("rankings", sa.Column("check_status", sa.String(length=20), nullable=True))
    _add_column_if_missing("rankings", sa.Column("error_message", sa.Text(), nullable=True))

    op.execute("UPDATE rankings SET language = 'en' WHERE language IS NULL OR language = ''")
    op.execute("""
        UPDATE rankings
        SET check_status = CASE WHEN position IS NULL THEN 'not_found' ELSE 'found' END
        WHERE check_status IS NULL OR check_status = ''
    """)
    op.alter_column("rankings", "language", nullable=False, server_default="en")
    op.alter_column("rankings", "check_status", nullable=False, server_default="not_found")


def downgrade():
    # Preserve ranking history on downgrade.
    pass
