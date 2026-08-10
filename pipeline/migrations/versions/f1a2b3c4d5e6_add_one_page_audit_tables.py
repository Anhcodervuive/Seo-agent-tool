"""add persistent one-page audit tables

Revision ID: f1a2b3c4d5e6
Revises: d8c88ac452ce
Create Date: 2026-08-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'd8c88ac452ce'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'one_page_audits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('normalized_url', sa.Text(), nullable=False),
        sa.Column('target_keyword', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('summary', sa.JSON(), nullable=True),
        sa.Column('page_data', sa.JSON(), nullable=True),
        sa.Column('pdf_path', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('source_crawl_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('one_page_audits') as batch_op:
        batch_op.create_index('ix_one_page_audits_client_id', ['client_id'], unique=False)
        batch_op.create_index('ix_one_page_audits_created_by_user_id', ['created_by_user_id'], unique=False)
        batch_op.create_index('ix_one_page_audits_normalized_url', ['normalized_url'], unique=False)
        batch_op.create_index('ix_one_page_audits_status', ['status'], unique=False)
        batch_op.create_index('ix_one_page_audits_created_at', ['created_at'], unique=False)

    op.create_table(
        'one_page_findings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audit_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('finding_key', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['audit_id'], ['one_page_audits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('one_page_findings') as batch_op:
        batch_op.create_index('ix_one_page_findings_audit_id', ['audit_id'], unique=False)
        batch_op.create_index('ix_one_page_findings_category', ['category'], unique=False)

    op.create_table(
        'one_page_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audit_id', sa.Integer(), nullable=False),
        sa.Column('metric_key', sa.String(length=128), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(['audit_id'], ['one_page_audits.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('audit_id', 'metric_key', name='uq_one_page_metric_audit_key'),
    )
    with op.batch_alter_table('one_page_metrics') as batch_op:
        batch_op.create_index('ix_one_page_metrics_audit_id', ['audit_id'], unique=False)


def downgrade():
    op.drop_table('one_page_metrics')
    op.drop_table('one_page_findings')
    op.drop_table('one_page_audits')
