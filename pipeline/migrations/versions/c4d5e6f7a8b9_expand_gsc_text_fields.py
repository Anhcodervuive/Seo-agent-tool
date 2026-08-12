"""expand cached Search Console text fields

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-12 16:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'gsc_metrics',
        'query',
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        'gsc_metrics',
        'page',
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        'gsc_metrics',
        'page',
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        'gsc_metrics',
        'query',
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
