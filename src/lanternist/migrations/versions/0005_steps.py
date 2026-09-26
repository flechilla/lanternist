"""steps: the hosted edition's step cache, one record per owner and step key, and the `shared` user who
owns the records of what everyone shares (voice samples)

A local library gets the table empty: its step records stay JSON files beside its assets, where they are.

Revision ID: 0005
Revises: 0004
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    users = sa.table(
        "users",
        sa.column("id", sa.String),
        sa.column("auth_subject", sa.String),
        sa.column("role", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    created = datetime.now(UTC).replace(tzinfo=None)
    op.bulk_insert(users, [{"id": "shared", "auth_subject": "shared", "role": "user", "created_at": created}])
    op.create_table(
        "steps",
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_steps_owner_id"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("record", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=True),
        sa.PrimaryKeyConstraint("owner_id", "key", name="pk_steps"),
    )


def downgrade():
    op.drop_table("steps")
    op.execute("DELETE FROM users WHERE id = 'shared'")
