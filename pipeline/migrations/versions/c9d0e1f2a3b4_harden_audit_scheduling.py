"""harden audit scheduling and worker recovery

Revision ID: c9d0e1f2a3b4
Revises: b1c2d3e4f5a6
Create Date: 2026-08-16 08:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def _add_column_if_missing(table, column):
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def upgrade():
    _add_column_if_missing("audit_schedules", sa.Column("run_at_local", sa.String(length=5), nullable=False, server_default="02:00"))
    _add_column_if_missing("audit_jobs", sa.Column("scheduled_for", sa.DateTime(), nullable=True))
    _add_column_if_missing("audit_jobs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("audit_jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    _add_column_if_missing("audit_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    _add_column_if_missing("audit_jobs", sa.Column("available_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("audit_jobs", sa.Column("retry_of_job_id", sa.Integer(), nullable=True))

    # Preserve the wall-clock time visible to users for schedules that already
    # have a next occurrence; disabled schedules keep the safe 02:00 default.
    op.execute("""
        UPDATE audit_schedules
        SET run_at_local = to_char(
            (next_run_at AT TIME ZONE 'UTC') AT TIME ZONE timezone,
            'HH24:MI'
        )
        WHERE next_run_at IS NOT NULL
    """)

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys("audit_jobs")
    if not any(fk.get("constrained_columns") == ["retry_of_job_id"] for fk in foreign_keys):
        op.create_foreign_key("fk_audit_jobs_retry_of", "audit_jobs", "audit_jobs", ["retry_of_job_id"], ["id"], ondelete="SET NULL")

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("audit_jobs")}
    if "ix_audit_jobs_heartbeat_at" not in indexes:
        op.create_index("ix_audit_jobs_heartbeat_at", "audit_jobs", ["heartbeat_at"])
    if "ix_audit_jobs_available_at" not in indexes:
        op.create_index("ix_audit_jobs_available_at", "audit_jobs", ["available_at"])
    if "ix_audit_jobs_retry_of_job_id" not in indexes:
        op.create_index("ix_audit_jobs_retry_of_job_id", "audit_jobs", ["retry_of_job_id"])

    constraints = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("audit_jobs")}
    if "uq_audit_jobs_schedule_occurrence" not in constraints:
        op.create_unique_constraint("uq_audit_jobs_schedule_occurrence", "audit_jobs", ["schedule_id", "scheduled_for"])
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_audit_jobs_active_client ON audit_jobs (client_id) WHERE status IN ('pending', 'running')")


def downgrade():
    # Durable scheduling data is intentionally preserved on downgrade.
    pass
