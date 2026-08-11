"""add competitor ownership to rankings and backlinks

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7b8c9d0e1f2'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rankings') as batch_op:
        batch_op.add_column(sa.Column('competitor_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_rankings_competitor_id', ['competitor_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_rankings_competitor_id',
            'competitors',
            ['competitor_id'],
            ['id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table('backlink_history') as batch_op:
        batch_op.add_column(sa.Column('competitor_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_backlink_history_competitor_id', ['competitor_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_backlink_history_competitor_id',
            'competitors',
            ['competitor_id'],
            ['id'],
            ondelete='CASCADE',
        )


def downgrade():
    with op.batch_alter_table('backlink_history') as batch_op:
        batch_op.drop_constraint('fk_backlink_history_competitor_id', type_='foreignkey')
        batch_op.drop_index('ix_backlink_history_competitor_id')
        batch_op.drop_column('competitor_id')

    with op.batch_alter_table('rankings') as batch_op:
        batch_op.drop_constraint('fk_rankings_competitor_id', type_='foreignkey')
        batch_op.drop_index('ix_rankings_competitor_id')
        batch_op.drop_column('competitor_id')
