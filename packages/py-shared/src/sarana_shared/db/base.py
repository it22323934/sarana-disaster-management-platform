"""DeclarativeBase with created_at/updated_at mixins, and the shared column types every
service's ORM models build on.

The actual domain tables (admin hierarchy, hazard, alerting, incident, aid, resilience,
audit) are docs/build-prompts/04-data-model.md's job — out of scope here per
docs/build-prompts/03-monorepo-scaffold.md ("Do not create domain tables here").
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sarana_shared.domain.ids import uuid7


class Base(DeclarativeBase):
    """Every service's ORM models inherit from this, not from sqlalchemy.orm.DeclarativeBase
    directly, so a single metadata/naming-convention change here reaches every service."""


class UUIDPrimaryKeyMixin:
    """Every entity's PK is a UUIDv7 per docs/build-prompts/02-conventions.md — time-ordered,
    index-friendly, generated application-side so it's available before flush."""

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    """created_at / updated_at, per the naming convention. Always server-side `now()` so
    clock skew between app instances can never produce an out-of-order timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
