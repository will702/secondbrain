import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, enum_col, uuid_pk
from app.models.enums import GoalHorizon, GoalStatus


class Goal(TimestampMixin, Base):
    """A target for a period. Progress is DERIVED (completed linked tasks in the
    window + manual check-ins), never stored, so it cannot go stale."""

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    why: Mapped[str | None]
    horizon: Mapped[GoalHorizon] = mapped_column(
        enum_col(GoalHorizon), nullable=False, default=GoalHorizon.week
    )
    metric: Mapped[str] = mapped_column(sa.Text, nullable=False, default="tasks")
    unit: Mapped[str] = mapped_column(sa.Text, nullable=False, default="tasks")
    target_value: Mapped[float] = mapped_column(sa.Float, nullable=False)
    starts_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    due_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    status: Mapped[GoalStatus] = mapped_column(
        enum_col(GoalStatus), nullable=False, default=GoalStatus.active
    )
    parent_goal_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("goals.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(sa.Text, nullable=False, default="user")
    provenance: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (sa.Index("goals_user_due_idx", "user_id", "due_on"),)


class GoalCheckin(Base):
    __tablename__ = "goal_checkins"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delta: Mapped[float] = mapped_column(sa.Float, nullable=False)
    note: Mapped[str | None]
    source: Mapped[str] = mapped_column(sa.Text, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
