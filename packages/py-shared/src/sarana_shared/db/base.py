"""Declarative base, naming conventions and the mixins every table uses.

Conventions: snake_case, tables singular (`incident`, not `incidents`), PK `id`,
FKs `{table}_id`, timestamps `created_at` / `updated_at` / `{verb}_at`.

ADR-002: one PostgreSQL, schema per service. A model sets its schema through
`__table_args__ = {"schema": "incident"}` (or the service's `ServiceBase` subclass).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from sarana_shared.domain.ids import uuid7

# Deterministic constraint names. Without these, alembic autogenerate produces
# unnameable constraints and a downgrade cannot drop what an upgrade created.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root declarative base shared by every service."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def as_dict(self) -> dict[str, Any]:
        """Column values as a plain dict. Debugging and test assertions only."""
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self) -> str:
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class UUIDPrimaryKeyMixin:
    """A UUIDv7 primary key named `id`.

    Time-ordered, so it clusters well in a btree and carries its own creation time -
    see `sarana_shared.domain.ids.uuid7_timestamp`.
    """

    @declared_attr.directive
    def id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - SQLAlchemy declared_attr signature
        return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    """`created_at` and `updated_at`, both timestamptz, both server-defaulted.

    Server-side defaults so that a migration or a psql session writing directly still
    produces correct timestamps.
    """

    @declared_attr.directive
    def created_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )

    @declared_attr.directive
    def updated_at(cls) -> Mapped[datetime]:  # noqa: N805
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )


class CorrelationMixin:
    """The correlation ID that produced this row.

    Every write that originates from a citizen report carries the same correlation ID
    from intake through to disbursement. Storing it on the row is what lets an auditor
    reconstruct the chain without joining through the event log.
    """

    @declared_attr.directive
    def correlation_id(cls) -> Mapped[str]:  # noqa: N805
        from sqlalchemy import String

        return mapped_column(String(64), nullable=False, index=True)
