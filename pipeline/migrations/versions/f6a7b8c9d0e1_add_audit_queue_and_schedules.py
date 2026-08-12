"""add durable audit queue and schedules

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-13 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('frequency', sa.String(length=16), nullable=False, server_default='weekly'),
        sa.Column('run_type', sa.String(length=32), nullable=False, server_default='full_audit'),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='Asia/Kolkata'),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('client_id'),
    )
    op.create_index('ix_audit_schedules_client_id', 'audit_schedules', ['client_id'], unique=True)
    op.create_index('ix_audit_schedules_next_run_at', 'audit_schedules', ['next_run_at'], unique=False)

    op.create_table(
        'audit_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('schedule_id', sa.Integer(), nullable=True),
        sa.Column('run_type', sa.String(length=32), nullable=False, server_default='full_audit'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['schedule_id'], ['audit_schedules.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_id'),
    )
    op.create_index('ix_audit_jobs_client_id', 'audit_jobs', ['client_id'], unique=False)
    op.create_index('ix_audit_jobs_snapshot_id', 'audit_jobs', ['snapshot_id'], unique=True)
    op.create_index('ix_audit_jobs_schedule_id', 'audit_jobs', ['schedule_id'], unique=False)
    op.create_index('ix_audit_jobs_status', 'audit_jobs', ['status'], unique=False)
    op.create_index('ix_audit_jobs_queued_at', 'audit_jobs', ['queued_at'], unique=False)


def downgrade():
    op.drop_table('audit_jobs')
    op.drop_table('audit_schedules')
