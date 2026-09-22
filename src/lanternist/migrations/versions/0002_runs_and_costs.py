"""step runs, prices, settings, uploads; job estimates and story budgets

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("estimate", sa.JSON, nullable=True))
    with op.batch_alter_table("stories") as b:
        b.add_column(sa.Column("budget_micros", sa.BigInteger, nullable=True))
    op.create_table(
        "step_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "story_id",
            sa.String(32),
            sa.ForeignKey("stories.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
        ),
        sa.Column("scene", sa.Integer, nullable=True),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("step_key", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("urls", sa.JSON, nullable=True),
        sa.Column("units", sa.Float, nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("cost_micros", sa.BigInteger, nullable=True),
        sa.Column("cost_source", sa.String(16), nullable=False),
        sa.Column("estimate_micros", sa.BigInteger, nullable=True),
        sa.Column("gpu_seconds", sa.Float, nullable=True),
        sa.Column("wall_seconds", sa.Float, nullable=True),
        sa.Column("meta", sa.JSON, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("finished_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_step_runs_key_status", "step_runs", ["step_key", "status"])
    op.create_index("ix_step_runs_provider_created", "step_runs", ["provider", "created_at"])
    op.create_table(
        "model_prices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(200), nullable=False, index=True),
        sa.Column("endpoint", sa.String(200), nullable=True),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("unit_price", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("synced_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.JSON, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("asset", sa.String(80), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("provider", "asset"),
    )


def downgrade():
    with op.batch_alter_table("stories") as b:
        b.drop_column("budget_micros")
    with op.batch_alter_table("jobs") as b:
        b.drop_column("estimate")
    op.drop_table("uploads")
    op.drop_table("settings")
    op.drop_table("model_prices")
    op.drop_index("ix_step_runs_provider_created", "step_runs")
    op.drop_index("ix_step_runs_key_status", "step_runs")
    op.drop_table("step_runs")
