"""Delegate snapshot cleanup to PostgreSQL cascades.

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
"""

import sqlalchemy as sa
from alembic import op


revision = "g4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


# These tables existed before their snapshot foreign keys had ON DELETE CASCADE.
# Replacing only these constraints keeps the migration narrowly scoped while
# allowing a parent snapshot delete to be performed entirely by PostgreSQL.
SNAPSHOT_FOREIGN_KEYS = (
    ("crawl_issues", "snapshot_id"),
    ("crawl_pages", "snapshot_id"),
    ("crawl_page_links", "snapshot_id"),
    ("crawl_page_images", "snapshot_id"),
    ("crawl_page_structured_data", "snapshot_id"),
    ("ga4_metrics", "snapshot_id"),
    ("gsc_metrics", "snapshot_id"),
    ("rankings", "snapshot_id"),
    ("backlink_history", "snapshot_id"),
)

# The older, high-volume tables also need an indexed foreign key for the
# PostgreSQL cascade checks to remain fast as snapshot history grows.
SNAPSHOT_INDEXES = (
    ("crawl_issues", "ix_crawl_issues_snapshot_id"),
    ("ga4_metrics", "ix_ga4_metrics_snapshot_id"),
    ("gsc_metrics", "ix_gsc_metrics_snapshot_id"),
    ("rankings", "ix_rankings_snapshot_id"),
    ("backlink_history", "ix_backlink_history_snapshot_id"),
)


def _snapshot_foreign_key_names(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return [
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys(table_name)
        if foreign_key.get("name")
        and foreign_key.get("constrained_columns") == [column_name]
        and foreign_key.get("referred_table") == "snapshots"
        and foreign_key.get("referred_columns") == ["id"]
    ]


def _replace_snapshot_foreign_key(table_name, column_name, ondelete=None):
    for constraint_name in _snapshot_foreign_key_names(table_name, column_name):
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    op.create_foreign_key(
        f"fk_{table_name}_{column_name}_snapshots",
        table_name,
        "snapshots",
        [column_name],
        ["id"],
        ondelete=ondelete,
    )


def _create_index_if_missing(table_name, index_name):
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, ["snapshot_id"], unique=False)


def upgrade():
    for table_name, column_name in SNAPSHOT_FOREIGN_KEYS:
        _replace_snapshot_foreign_key(table_name, column_name, ondelete="CASCADE")

    for table_name, index_name in SNAPSHOT_INDEXES:
        _create_index_if_missing(table_name, index_name)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table_name, index_name in SNAPSHOT_INDEXES:
        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)

    for table_name, column_name in SNAPSHOT_FOREIGN_KEYS:
        _replace_snapshot_foreign_key(table_name, column_name)
