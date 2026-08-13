"""allow independent full-audit and ranking schedules

Revision ID: a0b1c2d3e4f5
Revises: f6a7b8c9d0e1
Create Date: 2026-08-13 03:30:00.000000

"""
from alembic import op


revision = 'a0b1c2d3e4f5'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('audit_schedules_client_id_key', 'audit_schedules', type_='unique')
    op.drop_index('ix_audit_schedules_client_id', table_name='audit_schedules')
    op.create_unique_constraint(
        'uq_audit_schedules_client_run_type',
        'audit_schedules',
        ['client_id', 'run_type'],
    )


def downgrade():
    op.drop_constraint('uq_audit_schedules_client_run_type', 'audit_schedules', type_='unique')
    op.create_unique_constraint('audit_schedules_client_id_key', 'audit_schedules', ['client_id'])
    op.create_index('ix_audit_schedules_client_id', 'audit_schedules', ['client_id'], unique=True)
