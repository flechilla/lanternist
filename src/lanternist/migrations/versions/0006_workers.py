"""jobs held by workers: who holds a job and their last heartbeat, a cancel asked for while it runs, and
the owner's render slot it takes, unique per owner, so two claims can't both take a person's last one

A local library gets the columns empty: its running jobs are requeued at the next start anyway.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("worker", sa.String(64), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("cancel_requested_at", sa.DateTime, nullable=True))
        batch.add_column(sa.Column("slot", sa.Integer, nullable=True))
        batch.create_unique_constraint("uq_jobs_owner_id_slot", ["owner_id", "slot"])
        batch.create_check_constraint("ck_jobs_slot_running", "slot IS NULL OR status = 'running'")
        batch.create_index("ix_jobs_owner_id_started_at", ["owner_id", "started_at"])


def downgrade():
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_owner_id_started_at")
        batch.drop_constraint("ck_jobs_slot_running", type_="check")
        batch.drop_constraint("uq_jobs_owner_id_slot", type_="unique")
        batch.drop_column("slot")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("worker")
