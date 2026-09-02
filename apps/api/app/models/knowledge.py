import uuid
from datetime import date

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, enum_col, uuid_pk
from app.models.enums import EntityKind

settings = get_settings()


class Entity(TimestampMixin, Base):
    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EntityKind] = mapped_column(enum_col(EntityKind), nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None]
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    embedding = mapped_column(Vector(settings.embedding_dim))
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("entities.id"))

    __table_args__ = (
        sa.UniqueConstraint("user_id", "kind", "normalized_name", name="uq_entities_natural"),
        sa.Index("entities_user_kind_idx", "user_id", "kind"),
    )

    mentions: Mapped[list["EntityMention"]] = relationship(back_populates="entity")


class EntityRelationship(TimestampMixin, Base):
    __tablename__ = "entity_relationships"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    predicate: Mapped[str] = mapped_column(sa.Text, nullable=False)
    object_entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)

    subject = relationship("Entity", foreign_keys=[subject_entity_id])
    object = relationship("Entity", foreign_keys=[object_entity_id])

    __table_args__ = (
        sa.UniqueConstraint(
            "subject_entity_id", "predicate", "object_entity_id", name="uq_relationship_triple"
        ),
    )


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    surface_form: Mapped[str] = mapped_column(sa.Text, nullable=False)
    span_start: Mapped[int | None]
    span_end: Mapped[int | None]
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    created_at = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    entity = relationship("Entity", back_populates="mentions")
    chunk = relationship("DocumentChunk")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("entities.id"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False, default="project")
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="active")
    color: Mapped[str | None]
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]

    entity = relationship("Entity")


class Person(TimestampMixin, Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("entities.id"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    email: Mapped[str | None]
    organization: Mapped[str | None]
    role: Mapped[str | None]
    relationship: Mapped[str | None]

    entity = relationship("Entity")
