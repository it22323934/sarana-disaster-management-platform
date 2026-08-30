"""Database access for authentication.

All persistence goes through this module (ADR-002). The router orchestrates; nothing in
it writes SQL, so the queries that touch credentials are readable in one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core_api.domain.auth.sessions import StoredRefreshToken
from core_api.repo.admin import AppUser, GNDivision, Role, ServiceClient, UserRole
from core_api.repo.auth import Device, LoginAttempt, MFAEnrolment, OTPChallenge, RefreshToken
from sarana_shared.auth.scopes import Role as RoleCode
from sarana_shared.auth.scopes import RoleAssignment
from sarana_shared.domain.ids import ensure_correlation_id, uuid7
from sarana_shared.domain.time import utc_now


async def find_user_by_email(session: AsyncSession, email: str) -> AppUser | None:
    """Look up an account by email. Case-insensitive: nobody types their own casing twice."""
    result = await session.execute(select(AppUser).where(AppUser.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def find_user_by_phone_hash(session: AsyncSession, phone_hash: str) -> AppUser | None:
    """Look up a citizen account by the HMAC of their number."""
    result = await session.execute(select(AppUser).where(AppUser.phone_hash == phone_hash))
    return result.scalar_one_or_none()


async def load_role_assignments(session: AsyncSession, user_id: UUID) -> list[RoleAssignment]:
    """Every role this user holds, with the area each was granted in.

    Read fresh at token-mint time rather than cached on the account, so removing a role
    takes effect on the next token rather than whenever a cache happens to expire.
    """
    result = await session.execute(
        select(Role.code, UserRole.scope_type, UserRole.scope_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    return [
        RoleAssignment(role=RoleCode(code), scope_type=scope_type, scope_code=scope_code)
        for code, scope_type, scope_code in result
    ]


async def record_login_attempt(
    session: AsyncSession,
    *,
    account_hash: str,
    source_hash: str,
    succeeded: bool,
    correlation_id: str,
    failure_reason: str | None = None,
) -> None:
    """Append to the lockout trail. Both keys are HMACs, never plaintext."""
    session.add(
        LoginAttempt(
            id=uuid7(),
            account_hash=account_hash,
            source_hash=source_hash,
            succeeded=succeeded,
            failure_reason=failure_reason,
            correlation_id=correlation_id,
        )
    )


async def count_recent_failures(
    session: AsyncSession, *, account_hash: str, window: timedelta
) -> int:
    """Consecutive failures inside the window, for the backoff.

    Counts back to the most recent success: a login that worked clears the slate, so
    yesterday's typos do not compound with today's.
    """
    result = await session.execute(
        select(LoginAttempt.succeeded, LoginAttempt.attempted_at)
        .where(
            LoginAttempt.account_hash == account_hash,
            LoginAttempt.attempted_at >= utc_now() - window,
        )
        .order_by(LoginAttempt.attempted_at.desc())
    )

    failures = 0
    for succeeded, _attempted_at in result:
        if succeeded:
            break
        failures += 1
    return failures


async def upsert_device(
    session: AsyncSession, *, user_id: UUID, device_id: UUID | None, platform: str
) -> Device:
    """Find or create the device a session belongs to.

    Tokens are bound to a device so a lost handset can be revoked without ending every
    session the officer has, and so refresh reuse can be attributed to a family.
    """
    if device_id is not None:
        result = await session.execute(
            select(Device).where(Device.id == device_id, Device.user_id == user_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.last_seen_at = utc_now()
            return existing

    device = Device(id=uuid7(), user_id=user_id, platform=platform)
    session.add(device)
    await session.flush()
    return device


async def store_refresh_token(
    session: AsyncSession,
    *,
    token_id: UUID,
    user_id: UUID,
    device_id: UUID,
    family_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> None:
    """Persist the hash of a newly minted refresh token."""
    session.add(
        RefreshToken(
            id=token_id,
            user_id=user_id,
            device_id=device_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )


async def find_refresh_token(session: AsyncSession, token_hash: str) -> StoredRefreshToken | None:
    """Resolve a presented token by its hash."""
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return StoredRefreshToken(
        token_id=row.id,
        user_id=row.user_id,
        device_id=row.device_id,
        family_id=row.family_id,
        expires_at=row.expires_at,
        used_at=row.used_at,
        revoked_at=row.revoked_at,
    )


async def mark_rotated(session: AsyncSession, *, token_id: UUID, replacement_id: UUID) -> None:
    """Mark a refresh token used, pointing at what replaced it.

    The chain is what makes a reuse investigable: given a replayed token, an operator can
    walk forward to see which sessions descended from it.
    """
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == token_id)
        .values(used_at=utc_now(), rotated_to=replacement_id)
    )


async def revoke_family(session: AsyncSession, *, family_id: UUID, reason: str) -> int:
    """Revoke every live token descended from one login. Returns how many.

    Called on reuse detection. A replayed token means either the client retried or
    somebody else has a copy, and those are indistinguishable from here.
    """
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utc_now(), revoked_reason=reason)
        ),
    )
    return int(result.rowcount or 0)


async def revoke_device(session: AsyncSession, *, device_id: UUID, reason: str) -> None:
    """End every session on one device, and mark the device itself revoked."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.device_id == device_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utc_now(), revoked_reason=reason)
    )
    await session.execute(
        update(Device)
        .where(Device.id == device_id)
        .values(revoked_at=utc_now(), revoked_reason=reason)
    )


async def load_mfa_enrolment(session: AsyncSession, user_id: UUID) -> MFAEnrolment | None:
    """The user's confirmed second factor, if they have one."""
    result = await session.execute(select(MFAEnrolment).where(MFAEnrolment.user_id == user_id))
    return result.scalar_one_or_none()


async def recent_otp_sends(
    session: AsyncSession, *, msisdn_hash: str, window: timedelta
) -> list[datetime]:
    """When codes were last sent to this number, for the hourly rate limit."""
    result = await session.execute(
        select(OTPChallenge.created_at)
        .where(
            OTPChallenge.msisdn_hash == msisdn_hash,
            OTPChallenge.created_at >= utc_now() - window,
        )
        .order_by(OTPChallenge.created_at)
    )
    return [row[0] for row in result]


async def find_live_otp(session: AsyncSession, msisdn_hash: str) -> OTPChallenge | None:
    """The most recent unconsumed challenge for a number."""
    result = await session.execute(
        select(OTPChallenge)
        .where(
            OTPChallenge.msisdn_hash == msisdn_hash,
            OTPChallenge.consumed_at.is_(None),
        )
        .order_by(OTPChallenge.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_gn_division_code(session: AsyncSession, gn_division_id: UUID) -> str | None:
    """Resolve a division id to its official code, for a capability token."""
    result = await session.execute(select(GNDivision.code).where(GNDivision.id == gn_division_id))
    return result.scalar_one_or_none()


async def record_security_event(
    session: AsyncSession,
    *,
    kind: str,
    detail: dict[str, object],
    subject_id: UUID | None = None,
) -> None:
    """Raise something for whoever is on call.

    `detail` carries counts and flags, never personal data and never a credential - the
    same rule as anomaly rationales, because a security log is read by more people than
    the data it describes was ever meant for.
    """
    from core_api.repo.auth import SecurityEvent

    session.add(
        SecurityEvent(
            id=uuid7(),
            kind=kind,
            subject_id=subject_id,
            detail=detail,
            correlation_id=ensure_correlation_id(),
        )
    )


async def store_otp_challenge(
    session: AsyncSession,
    *,
    msisdn_hash: str,
    code_hash: str,
    language: str,
    expires_at: datetime,
    max_attempts: int,
) -> None:
    """Persist a challenge. The code is stored hashed, the number as an HMAC."""
    session.add(
        OTPChallenge(
            id=uuid7(),
            msisdn_hash=msisdn_hash,
            code_hash=code_hash,
            language=language,
            expires_at=expires_at,
            max_attempts=max_attempts,
            correlation_id=ensure_correlation_id(),
        )
    )


async def consume_otp_challenge(session: AsyncSession, challenge_id: UUID) -> None:
    """Burn a challenge so a correct code cannot be replayed."""
    await session.execute(
        update(OTPChallenge).where(OTPChallenge.id == challenge_id).values(consumed_at=utc_now())
    )


async def record_otp_attempt(session: AsyncSession, challenge_id: UUID) -> None:
    """Count a wrong guess against the challenge's three tries."""
    await session.execute(
        update(OTPChallenge)
        .where(OTPChallenge.id == challenge_id)
        .values(attempts=OTPChallenge.attempts + 1)
    )


async def upsert_mfa_enrolment(
    session: AsyncSession,
    *,
    user_id: UUID,
    secret_encrypted: bytes,
    recovery_code_hashes: list[str],
) -> None:
    """Store an unconfirmed enrolment, replacing any previous attempt.

    Unconfirmed on purpose: a mistyped QR scan must not lock someone out of their own
    account, so the secret is inert until they prove they can produce a code from it.
    """
    existing = await load_mfa_enrolment(session, user_id)
    if existing is not None:
        existing.secret_encrypted = secret_encrypted
        existing.recovery_code_hashes = recovery_code_hashes
        existing.confirmed_at = None
        return

    session.add(
        MFAEnrolment(
            id=uuid7(),
            user_id=user_id,
            secret_encrypted=secret_encrypted,
            recovery_code_hashes=recovery_code_hashes,
        )
    )


async def confirm_mfa_enrolment(session: AsyncSession, user_id: UUID) -> None:
    """Activate an enrolment once a code from it has verified."""
    await session.execute(
        update(MFAEnrolment)
        .where(MFAEnrolment.user_id == user_id)
        .values(confirmed_at=utc_now(), last_verified_at=utc_now())
    )


async def find_service_client(session: AsyncSession, client_id: str) -> ServiceClient | None:
    """Look up a machine credential by its public id.

    Returns inactive clients too. The caller checks `active` and refuses with the same
    message it uses for an unknown client, so a revoked credential and a made-up one are
    indistinguishable from outside - otherwise this endpoint tells an attacker which
    client ids are real.
    """
    result = await session.execute(
        select(ServiceClient).where(ServiceClient.client_id == client_id)
    )
    return result.scalar_one_or_none()


async def touch_service_client(session: AsyncSession, client_uuid: UUID) -> None:
    """Record that a credential was used.

    The only column `sarana_app` may update on this table. It is what makes "which of
    these credentials is still in use?" answerable before somebody revokes one and finds
    out the hard way.
    """
    await session.execute(
        update(ServiceClient).where(ServiceClient.id == client_uuid).values(last_used_at=utc_now())
    )
