import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, uuid_pk


class Note(TimestampMixin, Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False, default="note")
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    provenance: Mapped[dict | None] = mapped_column(JSONB)


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False, default="gmail")
    provider_message_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    thread_id: Mapped[str | None]
    from_email: Mapped[str | None]
    from_name: Mapped[str | None]
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    subject: Mapped[str | None]
    body_text: Mapped[str | None]
    snippet: Mapped[str | None]
    received_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    importance: Mapped[float | None]
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    raw: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("user_id", "provider", "provider_message_id", name="uq_email_msg"),
    )


class StudyConcept(TimestampMixin, Base):
    __tablename__ = "study_concepts"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("entities.id"))
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None]
    mastery: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("study_concepts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    score: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
