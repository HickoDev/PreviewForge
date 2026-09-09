"""Create the task schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_tasks"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('todo', 'in_progress', 'done')", name="ck_task_status"),
        sa.CheckConstraint("length(trim(title)) > 0", name="ck_task_title"),
    )


def downgrade():
    op.drop_table("tasks")
