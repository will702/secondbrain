import enum
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def enum_col(enum_cls: type[enum.Enum], length: int = 32) -> sa.Enum:
    """Non-native enum stored as VARCHAR + CHECK with the lowercase member values."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda x: [e.value for e in x],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(),
        nullable=False,
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )
