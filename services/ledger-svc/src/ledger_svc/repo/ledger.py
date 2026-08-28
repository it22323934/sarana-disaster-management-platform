"""The Transparent Aid Ledger: approvals, disbursements, and the external anchor.

`disbursement` carries the second of the two mandatory human gates: releasing a financial
disbursement. `released_by` is NOT NULL, and the migration revokes UPDATE and DELETE from
the application role and installs an append-only trigger on top. Corrections are new
compensating entries, never edits.

ADR-005: a hash chain inside a database you control proves nothing, because the operator
can recompute the whole chain after tampering. `ledger_anchor` closes that hole - a daily
Merkle root written to S3 Object Lock in compliance mode, immutable even to the account
root user, published on the public dashboard and checkable by anyone with the
`sarana-verify` CLI and no privileged access at all.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from ledger_svc.repo.base import (
    AID_SCHEMA,
    APPROVAL_DECISIONS,
    APPROVAL_LEVELS,
    PAYMENT_RAILS,
)
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One approval decision at one level, hash-chained.

    DS approves; District Secretariat gives second-level approval above a configurable
    threshold. Each decision names its approver and its reason, and the chain makes the
    sequence of decisions tamper-evident.
    """

    __tablename__ = "approval"
    __table_args__ = (
        UniqueConstraint("entitlement_id", "level", name="uq_approval_entitlement_level"),
        CheckConstraint(in_list("level", APPROVAL_LEVELS), name="level_known"),
        CheckConstraint(in_list("decision", APPROVAL_DECISIONS), name="decision_known"),
        # A refusal that gives no reason is not reviewable, and the household has no
        # grounds on which to raise a grievance.
        CheckConstraint("decision = 'APPROVED' OR reason IS NOT NULL", name="refusal_has_a_reason"),
        Index("ix_approval_seq", "seq"),
        {"schema": AID_SCHEMA},
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    entitlement_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{AID_SCHEMA}.entitlement.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    level: Mapped[str] = mapped_column(String(12), nullable=False)
    approver_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(12), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


class Disbursement(UUIDPrimaryKeyMixin, Base):
    """Money actually released. HUMAN GATE, append-only, hash-chained.

    No `updated_at` and no update path of any kind. A mistake is corrected by a new
    compensating entry that references this one, which is what leaves the original
    visible to an auditor instead of overwritten.

    `citizen_confirmed` closes the loop from the other end: the household says whether the
    money arrived. A ledger that only records what the state believes it paid is not
    evidence that anyone was paid.
    """

    __tablename__ = "disbursement"
    __table_args__ = (
        UniqueConstraint("entitlement_id", name="uq_disbursement_entitlement"),
        CheckConstraint(in_list("payment_rail", PAYMENT_RAILS), name="payment_rail_known"),
        CheckConstraint("amount_lkr_cents > 0", name="amount_positive"),
        CheckConstraint(
            "citizen_confirmed = false OR citizen_confirmed_at IS NOT NULL",
            name="confirmation_is_timestamped",
        ),
        Index("ix_disbursement_seq", "seq"),
        Index("ix_disbursement_released_at", "released_at"),
        {"schema": AID_SCHEMA},
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False, unique=True)
    entitlement_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{AID_SCHEMA}.entitlement.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_lkr_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # The gate. Never nullable, never defaulted, never set by an agent.
    released_by: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment_rail: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    citizen_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    citizen_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    citizen_confirm_channel: Mapped[str | None] = mapped_column(String(16), nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerAnchor(UUIDPrimaryKeyMixin, Base):
    """A daily Merkle root over the disbursements closed that day (ADR-005).

    The root is written to S3 Object Lock in compliance mode with a retention period, so
    it cannot be altered by anyone - including the account root user - and published both
    on the transparency dashboard and in a public JSON feed.

    This is roughly two hundred lines of work across the platform, and it is the whole
    difference between "auditable" and "auditable by us".
    """

    __tablename__ = "ledger_anchor"
    __table_args__ = (
        UniqueConstraint("anchor_date", name="uq_ledger_anchor_date"),
        CheckConstraint("entry_count > 0", name="anchor_covers_entries"),
        CheckConstraint("last_seq >= first_seq", name="seq_range_ordered"),
        CheckConstraint("merkle_root ~ '^[0-9a-f]{64}$'", name="merkle_root_is_sha256"),
        CheckConstraint(
            "prev_anchor_hash IS NULL OR prev_anchor_hash ~ '^[0-9a-f]{64}$'",
            name="prev_anchor_hash_is_sha256",
        ),
        {"schema": AID_SCHEMA},
    )

    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    merkle_root: Mapped[str] = mapped_column(Text, nullable=False)
    prev_anchor_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="The previous day's anchor_hash. Chaining the days means removing a whole "
        "day is as detectable as altering one row inside it.",
    )
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    s3_object_lock_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
