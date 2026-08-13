"""repair missing audit queue tables

Some early production deployments were stamped at the latest Alembic revision
before the audit queue tables had been created.  This defensive migration makes
the schema self-healing without changing or deleting any existing audit data.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-08-13 11:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

from app.models import AuditJob, AuditSchedule


revision = "b1c2d3e4f5a6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # checkfirst preserves healthy deployments and creates the exact current
    # model/index definitions only when an earlier deployment missed them.
    if not inspector.has_table(AuditSchedule.__tablename__):
        AuditSchedule.__table__.create(bind, checkfirst=True)
        inspector = sa.inspect(bind)

    if not inspector.has_table(AuditJob.__tablename__):
        AuditJob.__table__.create(bind, checkfirst=True)


def downgrade():
    # Do not drop durable jobs or schedules during a downgrade.
    pass
