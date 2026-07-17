"""reconcile production schema

Revision ID: b29d5f31a7d4
Revises: d76b8653f35a
Create Date: 2026-07-17 17:16:00.000000

"""
from alembic import op
import sqlalchemy as sa

from app.models import GoogleAccountConfig, ProjectAISetting


# revision identifiers, used by Alembic.
revision = 'b29d5f31a7d4'
down_revision = 'd76b8653f35a'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(ProjectAISetting.__tablename__):
        ProjectAISetting.__table__.create(bind, checkfirst=True)

    if not inspector.has_table(GoogleAccountConfig.__tablename__):
        GoogleAccountConfig.__table__.create(bind, checkfirst=True)
        inspector = sa.inspect(bind)

    client_columns = {column["name"] for column in inspector.get_columns("clients")}
    if "google_account_id" not in client_columns:
        with op.batch_alter_table("clients") as batch_op:
            batch_op.add_column(sa.Column("google_account_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)

    account_columns = {column["name"] for column in inspector.get_columns("google_account_configs")}
    if "stored_filename" not in account_columns:
        with op.batch_alter_table("google_account_configs") as batch_op:
            batch_op.add_column(sa.Column("stored_filename", sa.String(length=255), nullable=True))
        inspector = sa.inspect(bind)

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("clients") if fk.get("name")}
    if "fk_clients_google_account_id_google_account_configs" not in fk_names:
        with op.batch_alter_table("clients") as batch_op:
            batch_op.create_foreign_key(
                "fk_clients_google_account_id_google_account_configs",
                "google_account_configs",
                ["google_account_id"],
                ["id"],
            )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("clients"):
        fk_names = {fk["name"] for fk in inspector.get_foreign_keys("clients") if fk.get("name")}
        if "fk_clients_google_account_id_google_account_configs" in fk_names:
            with op.batch_alter_table("clients") as batch_op:
                batch_op.drop_constraint("fk_clients_google_account_id_google_account_configs", type_="foreignkey")

        client_columns = {column["name"] for column in inspector.get_columns("clients")}
        if "google_account_id" in client_columns:
            with op.batch_alter_table("clients") as batch_op:
                batch_op.drop_column("google_account_id")

    if inspector.has_table("google_account_configs"):
        account_columns = {column["name"] for column in inspector.get_columns("google_account_configs")}
        if "stored_filename" in account_columns:
            with op.batch_alter_table("google_account_configs") as batch_op:
                batch_op.drop_column("stored_filename")

        GoogleAccountConfig.__table__.drop(bind, checkfirst=True)

    if inspector.has_table("project_ai_settings"):
        ProjectAISetting.__table__.drop(bind, checkfirst=True)
