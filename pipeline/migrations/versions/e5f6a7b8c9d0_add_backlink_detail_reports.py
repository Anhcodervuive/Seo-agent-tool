"""add detailed backlink snapshot reports

Revision ID: e5f6a7b8c9d0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-12 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'backlink_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('source_domain', sa.String(length=255), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('domain_rank', sa.Integer(), nullable=True),
        sa.Column('anchor_text', sa.Text(), nullable=True),
        sa.Column('target_url', sa.Text(), nullable=True),
        sa.Column('is_dofollow', sa.Boolean(), nullable=True),
        sa.Column('first_seen', sa.String(length=64), nullable=True),
        sa.Column('last_seen', sa.String(length=64), nullable=True),
        sa.Column('links_count', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backlink_items_snapshot_id', 'backlink_items', ['snapshot_id'], unique=False)
    op.create_index('ix_backlink_items_source_domain', 'backlink_items', ['source_domain'], unique=False)

    op.create_table(
        'backlink_referring_domains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('backlinks', sa.Integer(), nullable=True),
        sa.Column('domain_rank', sa.Integer(), nullable=True),
        sa.Column('domain_created_at', sa.String(length=64), nullable=True),
        sa.Column('domain_age_years', sa.Float(), nullable=True),
        sa.Column('first_seen', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backlink_referring_domains_snapshot_id', 'backlink_referring_domains', ['snapshot_id'], unique=False)
    op.create_index('ix_backlink_referring_domains_domain', 'backlink_referring_domains', ['domain'], unique=False)

    op.create_table(
        'backlink_anchors',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('anchor_text', sa.Text(), nullable=True),
        sa.Column('referring_domains', sa.Integer(), nullable=True),
        sa.Column('backlinks', sa.Integer(), nullable=True),
        sa.Column('first_seen', sa.String(length=64), nullable=True),
        sa.Column('lost_date', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_backlink_anchors_snapshot_id', 'backlink_anchors', ['snapshot_id'], unique=False)


def downgrade():
    op.drop_table('backlink_anchors')
    op.drop_table('backlink_referring_domains')
    op.drop_table('backlink_items')
