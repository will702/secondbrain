"""goals, goal check-ins, tasks.goal_id

Revision ID: a4d9c0e17b25
Revises: 8c2a61f4d9b0
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a4d9c0e17b25"
down_revision = "8c2a61f4d9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("horizon", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False, server_default="tasks"),
        sa.Column("unit", sa.Text(), nullable=False, server_default="tasks"),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parent_goal_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="user"),
        sa.Column("provenance", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_goal_id"], ["goals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_index("goals_user_due_idx", "goals", ["user_id", "due_on"])
    op.create_table(
        "goal_checkins",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goal_checkins_goal_id", "goal_checkins", ["goal_id"])
    op.add_column("tasks", sa.Column("goal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("tasks_goal_id_fkey", "tasks", "goals", ["goal_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_goal_id", table_name="tasks")
    op.drop_constraint("tasks_goal_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "goal_id")
    op.drop_index("ix_goal_checkins_goal_id", table_name="goal_checkins")
    op.drop_table("goal_checkins")
    op.drop_index("goals_user_due_idx", table_name="goals")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
