"""baseline schema

Revision ID: d76b8653f35a
Revises: 
Create Date: 2026-07-17 16:22:59.855980

"""
from alembic import op

from app.models import db


# revision identifiers, used by Alembic.
revision = 'd76b8653f35a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    db.metadata.create_all(bind=bind, checkfirst=True)


def downgrade():
    bind = op.get_bind()
    db.metadata.drop_all(bind=bind, checkfirst=True)
