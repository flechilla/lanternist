"""jobs without a story: a voice sample belongs to no story

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as b:
        b.alter_column("story_id", existing_type=sa.String(32), nullable=True)


def downgrade():
    # A job with no story (a voice sample) has nowhere to go in the older schema.
    op.execute("DELETE FROM jobs WHERE story_id IS NULL")
    with op.batch_alter_table("jobs") as b:
        b.alter_column("story_id", existing_type=sa.String(32), nullable=False)
