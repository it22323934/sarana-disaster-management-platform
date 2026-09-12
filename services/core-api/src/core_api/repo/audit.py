"""The `audit` schema: the append-only, hash-chained record of who did what.

Non-negotiable #4: every agent action and every human decision is written here. Same
chain trigger and same revoked grants as the aid ledger - an audit log the operator can
quietly edit is not an audit log.

`before` and `after` hold the changed state. They pass through the same redaction as the
structured logs before they are written: an audit entry must be enough to reconstruct a
decision without being a second copy of the personal data behind it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core_api.repo.base import AUDIT_SCHEMA
from sarana_shared.db.base import Base, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list

ACTOR_TYPES = ("AGENT", "HUMAN", "SYSTEM")


class AuditEntry(UUIDPrimaryKeyMixin, Base):
    """One recorded action.

    No `updated_at` and no update trigger: an entry is written once. A correction is a
    new entry describing the correction.
    """

    __tablename__ = "audit_entry"
    __table_args__ = (
        CheckConstraint(in_list("actor_type", ACTOR_TYPES), name="actor_type_known"),
        # An agent action must name its agent; a human action must name the human.
        CheckConstraint(
            "(actor_type = 'AGENT' AND agent_name IS NOT NULL)"
            " OR (actor_type = 'HUMAN' AND actor_id IS NOT NULL)"
            " OR actor_type = 'SYSTEM'",
            name="actor_identified",
        ),
        Index("ix_audit_entry_subject", "subject_type", "subject_id"),
        Index("ix_audit_entry_correlation", "correlation_id"),
        Index("ix_audit_entry_occurred_at", "occurred_at"),
        Index("ix_audit_entry_thread", "langgraph_thread_id"),
        {"schema": AUDIT_SCHEMA},
    )

    # The chain orders by seq, so it must be gapless and monotonic within the table.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    action: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(48), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    langgraph_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
