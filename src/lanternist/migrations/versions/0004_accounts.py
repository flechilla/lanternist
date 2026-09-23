"""accounts: users and their sign-in sessions, and an owner on every story, job, step run and setting

Every row already in a library goes to the local edition's one user, `local`, whom this migration
makes. The hosted edition runs it on an empty database.

Revision ID: 0004
Revises: 0003
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# What happens to an owned row when its owner is deleted: spend is kept, without the person.
OWNED = {"stories": "CASCADE", "jobs": "CASCADE", "step_runs": "SET NULL"}


def upgrade():
    users = op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("auth_subject", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("deleted_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("auth_subject", name="uq_users_auth_subject"),
    )
    created = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(users, [{"id": "local", "auth_subject": "local", "role": "user", "created_at": created}])
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id"),
            nullable=False,
        ),
        sa.Column("provider_session", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_provider_session", "sessions", ["provider_session"])

    # Added empty, filled, then required: a default of 'local' left in the schema would quietly give
    # a hosted row with no owner to the local user.
    for table, ondelete in OWNED.items():
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("owner_id", sa.String(32), nullable=True))
        op.execute(sa.table(table, sa.column("owner_id")).update().values(owner_id="local"))
        with op.batch_alter_table(table) as b:
            if ondelete == "CASCADE":
                b.alter_column("owner_id", existing_type=sa.String(32), nullable=False)
            b.create_foreign_key(f"fk_{table}_owner_id", "users", ["owner_id"], ["id"], ondelete=ondelete)
            b.create_index(f"ix_{table}_owner_id", ["owner_id"])

    # The owner joins the primary key, so the table is built anew and renamed, its key named for that.
    op.create_table(
        "settings_new",
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_settings_owner_id"),
            nullable=False,
        ),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.PrimaryKeyConstraint("owner_id", "key", name="pk_settings"),
    )
    op.execute(
        "INSERT INTO settings_new (owner_id, key, value, updated_at) "
        "SELECT 'local', key, value, updated_at FROM settings"
    )
    op.drop_table("settings")
    op.rename_table("settings_new", "settings")


def downgrade():
    # Only the local user's settings fit the older one-row-per-key table. A hosted database with
    # several users loses who owns what: its downgrade is for development, not for production.
    op.create_table(
        "settings_old",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.PrimaryKeyConstraint("key", name="settings_pkey"),
    )
    op.execute(
        "INSERT INTO settings_old (key, value, updated_at) "
        "SELECT key, value, updated_at FROM settings WHERE owner_id = 'local'"
    )
    op.drop_table("settings")
    op.rename_table("settings_old", "settings")

    for table in reversed(OWNED):
        with op.batch_alter_table(table) as b:
            b.drop_index(f"ix_{table}_owner_id")
            b.drop_constraint(f"fk_{table}_owner_id", type_="foreignkey")
            b.drop_column("owner_id")

    op.drop_index("ix_sessions_provider_session", "sessions")
    op.drop_index("ix_sessions_user_id", "sessions")
    op.drop_table("sessions")
    op.drop_table("users")
