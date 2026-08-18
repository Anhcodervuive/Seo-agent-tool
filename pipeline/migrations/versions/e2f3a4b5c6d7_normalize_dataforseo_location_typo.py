"""Normalize the known invalid DataForSEO location typo.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from alembic import op


revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    # This is an unambiguous historical typo that caused DataForSEO to reject
    # requests.  Keep it data-only and limited to the exact bad value.
    op.execute("UPDATE clients SET location = 'United Kingdom' WHERE trim(location) = 'United Kingdon'")
    op.execute("UPDATE keywords SET location = 'United Kingdom' WHERE trim(location) = 'United Kingdon'")


def downgrade():
    # A spelling correction is intentionally irreversible.
    pass
