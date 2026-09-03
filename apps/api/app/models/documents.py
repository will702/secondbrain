import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, enum_col, uuid_pk
from app.models.enums import DocumentKind, DocumentStatus

settings = get_settings()


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha256: Mapped[str] = mapped_column(sa.Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(sa.Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(sa.Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    doc_kind: Mapped[DocumentKind] = mapped_column(
        enum_col(DocumentKind), nullable=False, default=DocumentKind.other
    )
    title: Mapped[str | None]
    topic: Mapped[str | None]
    summary: Mapped[str | None]
    importance: Mapped[float | None]
    project_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("projects.id"))
    page_count: Mapped[int | None]
    status: Mapped[DocumentStatus] = mapped_column(
        enum_col(DocumentStatus), nullable=False, default=DocumentStatus.received
    )
    error: Mapped[str | None]
    provenance: Mapped[dict | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (sa.UniqueConstraint("user_id", "sha256", name="uq_documents_user_sha"),)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    section: Mapped[str | None]
    page: Mapped[int | None]
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    token_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    embedding = mapped_column(Vector(settings.embedding_dim))
    tsv = mapped_column(TSVECTOR, sa.Computed("to_tsvector('english', text)", persisted=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_index"),
        sa.Index(
            "chunks_embedding_idx",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        sa.Index("chunks_tsv_idx", "tsv", postgresql_using="gin"),
    )
