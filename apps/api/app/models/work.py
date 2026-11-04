import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, enum_col, uuid_pk
from app.models.enums import CommitmentConfidence, DeadlineStatus, EventKind, TaskStatus


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None]
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("entities.id"))
    status: Mapped[TaskStatus] = mapped_column(
        enum_col(TaskStatus), nullable=False, default=TaskStatus.pending
    )
    priority: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=3)
    importance: Mapped[float | None]
    estimated_minutes: Mapped[int | None]
    minimum_session_minutes: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=30)
    difficulty: Mapped[int | None]
    splittable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    preferred_time_of_day: Mapped[str] = mapped_column(sa.Text, nullable=False, default="any")
    energy: Mapped[str] = mapped_column(sa.Text, nullable=False, default="medium")
    deadline_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("deadlines.id", ondelete="SET NULL", use_alter=True)
    )
    provenance: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("goals.id", ondelete="SET NULL"), index=True
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_no_self_dependency"),
    )


class Deadline(TimestampMixin, Base):
    __tablename__ = "deadlines"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), index=True)
    date_is_exact: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    raw_expression: Mapped[str] = mapped_column(sa.Text, nullable=False)
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False, default="Asia/Jakarta")
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.3)
    explicit: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    status: Mapped[DeadlineStatus] = mapped_column(
        enum_col(DeadlineStatus), nullable=False, default=DeadlineStatus.tentative
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="SET NULL")
    )
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Commitment(TimestampMixin, Base):
    __tablename__ = "commitments"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    direction: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence: Mapped[CommitmentConfidence] = mapped_column(
        enum_col(CommitmentConfidence), nullable=False, default=CommitmentConfidence.possible
    )
    person_entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("entities.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    deadline_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("deadlines.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="open")
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EventKind] = mapped_column(enum_col(EventKind), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False, default="Asia/Jakarta")
    location: Mapped[str | None]
    description: Mapped[str | None]
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False, default="local")
    provider_event_id: Mapped[str | None]
    task_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("tasks.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    editable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    source_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("action_proposals.id")
    )
    provenance: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        sa.Index("events_user_range_idx", "user_id", "starts_at"),
        sa.Index("events_provider_idx", "user_id", "provider", "provider_event_id"),
    )
