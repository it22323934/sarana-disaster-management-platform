"""Authentication state: devices, refresh-token families, OTP, lockout, security events.

Nothing here stores a credential in a form that is useful if the table leaks. Refresh
tokens are stored hashed, OTP codes are stored hashed, and the account and address a
login attempt was made against are stored as HMACs so the lockout table cannot be mined
for a list of officer emails or citizen phone numbers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from core_api.repo.base import ADMIN_SCHEMA
from sarana_shared.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from sarana_shared.db.constraints import in_list

DEVICE_PLATFORMS: tuple[str, ...] = ("ios", "android", "web", "field_companion")

REVOCATION_REASONS: tuple[str, ...] = (
    "LOGOUT",
    "ROTATED",
    "REUSE_DETECTED",
    "DEVICE_LOST",
    "ADMIN_REVOKED",
    "ROLE_CHANGED",
)

SECURITY_EVENT_KINDS: tuple[str, ...] = (
    "REFRESH_REUSE",
    "LOCKOUT_TRIGGERED",
    "REPEATED_AUTHZ_DENIAL",
    "LEDGER_DENIAL_BURST",
    "TOTP_FAILURE_BURST",
    "CAPABILITY_MISUSE",
)


class Device(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One installation of one app, on one handset.

    Tokens are bound to a device so a lost phone can be revoked without ending every
    session the officer has - and so refresh-token reuse can be attributed to a family
    rather than to an account.
    """

    __tablename__ = "device"
    __table_args__ = (
        CheckConstraint(in_list("platform", DEVICE_PLATFORMS), name="platform_known"),
        Index("ix_device_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
        {"schema": ADMIN_SCHEMA},
    )

    user_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(96), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """A single-use refresh token, stored hashed, in a rotating family.

    Rotation makes reuse detectable: presenting a token that has already been exchanged
    means either the client replayed it or someone else has a copy. Either way the whole
    family is revoked and a security event is raised, because the two cases are
    indistinguishable from here and only one of them is safe to ignore.
    """

    __tablename__ = "refresh_token"
    __table_args__ = (
        CheckConstraint(
            "revoked_reason IS NULL OR " + in_list("revoked_reason", REVOCATION_REASONS),
            name="revoked_reason_known",
        ),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_reason IS NOT NULL",
            name="revocation_has_a_reason",
        ),
        Index(
            "ix_refresh_token_live",
            "family_id",
            postgresql_where=text("revoked_at IS NULL AND used_at IS NULL"),
        ),
        {"schema": ADMIN_SCHEMA},
    )

    user_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.app_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.device.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Every token descended from one login shares a family. Reuse revokes the family.
    family_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_to: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)


class OTPChallenge(UUIDPrimaryKeyMixin, Base):
    """A one-time code sent to a citizen's phone.

    Citizens have no password. The MSISDN is the identity and the OTP is the proof, which
    is the only scheme that works for someone reporting a collapsed house from a borrowed
    handset.

    The code is stored hashed and the number as an HMAC, so this table is not a list of
    phone numbers and the codes in flight are not readable from it.
    """

    __tablename__ = "otp_challenge"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        CheckConstraint("language IN ('si','ta','en')", name="language_supported"),
        Index(
            "ix_otp_challenge_live",
            "msisdn_hash",
            postgresql_where=text("consumed_at IS NULL"),
        ),
        Index("ix_otp_challenge_created", "created_at"),
        {"schema": ADMIN_SCHEMA},
    )

    msisdn_hash: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Which language the message went out in. The household's preferred_language wins;
    # this records what was actually sent so a delivery complaint is answerable.
    language: Mapped[str] = mapped_column(String(2), nullable=False, server_default="si")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """One authentication attempt, for the per-account and per-address backoff.

    Both keys are HMACs. A lockout table that stored plaintext emails and IPs would be a
    directory of every officer in the country plus the addresses they work from, which is
    a worse leak than the passwords it is protecting.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_account_time", "account_hash", "attempted_at"),
        Index("ix_login_attempt_source_time", "source_hash", "attempted_at"),
        {"schema": ADMIN_SCHEMA},
    )

    account_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)


class SecurityEvent(UUIDPrimaryKeyMixin, Base):
    """Something that warrants a look from whoever is on call.

    Raised by refresh-token reuse, by repeated authorisation denials against ledger
    endpoints, and by a capability token being presented where it does not belong. The
    detail is JSONB and carries no personal data - the same rule as anomaly rationales,
    for the same reason.
    """

    __tablename__ = "security_event"
    __table_args__ = (
        CheckConstraint(in_list("kind", SECURITY_EVENT_KINDS), name="kind_known"),
        CheckConstraint("jsonb_typeof(detail) = 'object'", name="detail_is_object"),
        Index("ix_security_event_kind_time", "kind", "occurred_at"),
        {"schema": ADMIN_SCHEMA},
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[Any] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)


class MFAEnrolment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A confirmed second factor, and the recovery codes that survive a lost device.

    Kept out of `app_user` so a secret is never read by accident when loading an account
    for an unrelated reason. Recovery codes are stored hashed and single-use.
    """

    __tablename__ = "mfa_enrolment"
    __table_args__ = (
        CheckConstraint(
            "confirmed_at IS NULL OR confirmed_at >= created_at", name="confirmed_after_created"
        ),
        {"schema": ADMIN_SCHEMA},
    )

    user_id: Mapped[Any] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{ADMIN_SCHEMA}.app_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_code_hashes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
