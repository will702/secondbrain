import uuid
from datetime import datetime

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.core.db import Base
from app.models.base import JSONB, TimestampMixin, enum_col, uuid_pk
from app.models.enums import JobStatus, MemoryLayer, ProposalStatus, ReviewStatus, RiskLevel

settings = get_settings()


class Memory(TimestampMixin, Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    layer: Mapped[MemoryLayer] = mapped_column(enum_col(MemoryLayer), nullable=False)
    key: Mapped[str | None]
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    importance: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=0.5)
    embedding = mapped_column(Vector(settings.embedding_dim))
    access_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    provenance: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (sa.Index("memories_user_layer_idx", "user_id", "layer"),)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    agent: Mapped[str] = mapped_column(sa.Text, nullable=False)
    purpose: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="running")
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (sa.Index("agent_runs_user_idx", "user_id", "created_at"),)


class AIDecision(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent: Mapped[str] = mapped_column(sa.Text, nullable=False)
    decision: Mapped[str] = mapped_column(sa.Text, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class ActionProposal(Base):
    __tablename__ = "action_proposals"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    risk_level: Mapped[RiskLevel] = mapped_column(
        enum_col(RiskLevel), nullable=False, default=RiskLevel.low
    )
    proposed_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ProposalStatus] = mapped_column(
        enum_col(ProposalStatus), nullable=False, default=ProposalStatus.pending
    )
    expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (sa.Index("proposals_user_status_idx", "user_id", "status"),)


class ActionExecution(Base):
    __tablename__ = "action_executions"

    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("action_proposals.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    object_type: Mapped[str | None]
    object_id: Mapped[str | None]
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (sa.Index("audit_user_time_idx", "user_id", "created_at"),)


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, default="not_configured")
    encrypted_credentials: Mapped[str | None]
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    sync_cursor: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (sa.UniqueConstraint("user_id", "provider", name="uq_integration_provider"),)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None]
    type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_col(JobStatus), nullable=False, default=JobStatus.pending
    )
    run_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=3)
    last_error: Mapped[str | None]
    claimed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (sa.Index("jobs_ready_idx", "status", "run_at"),)


class ReviewItem(TimestampMixin, Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        enum_col(ReviewStatus), nullable=False, default=ReviewStatus.open
    )
    resolution: Mapped[dict | None] = mapped_column(JSONB)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)


class DocumentDerivation(Base):
    """A source edge from an uploaded document to one derived domain object."""

    __tablename__ = "document_derivations"

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), nullable=False)
    provenance: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "document_id", "object_type", "object_id", name="uq_document_derivation"
        ),
        sa.Index("derivations_object_idx", "object_type", "object_id"),
    )
