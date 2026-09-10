"""Durable export jobs and their repeatable report snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_exports"
down_revision = "0001_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("object_key", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'completed')", name="ck_export_status"),
    )


def downgrade():
    op.drop_table("exports")
