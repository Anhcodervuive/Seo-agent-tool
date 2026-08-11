"""add cached competitor insight reports

Revision ID: b3c4d5e6f7a8
Revises: a7b8c9d0e1f2
Create Date: 2026-08-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'competitor_insights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('competitor_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=True),
        sa.Column('target_domain', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('ranked_keywords', sa.JSON(), nullable=True),
        sa.Column('top_pages', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['competitor_id'], ['competitors.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('competitor_insights') as batch_op:
        batch_op.create_index('ix_competitor_insights_client_id', ['client_id'], unique=False)
        batch_op.create_index('ix_competitor_insights_competitor_id', ['competitor_id'], unique=False)
        batch_op.create_index('ix_competitor_insights_snapshot_id', ['snapshot_id'], unique=False)
        batch_op.create_index('ix_competitor_insights_status', ['status'], unique=False)
        batch_op.create_index('ix_competitor_insights_created_at', ['created_at'], unique=False)


def downgrade():
    op.drop_table('competitor_insights')
