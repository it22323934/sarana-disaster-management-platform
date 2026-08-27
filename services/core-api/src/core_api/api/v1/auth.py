"""Authentication endpoints.

Six actor types authenticate six different ways, and the differences are not incidental.
A citizen reporting a collapsed house from a borrowed handset has no email address and no
app installed; a GN officer three days into a cut-off division has no connectivity at
all. Each route here exists because one of those people could not use the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response, status

from core_api.api.deps import (
    KeyedHasherDep,
    PasswordDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    TokensDep,
)
from core_api.api.v1.schemas import (
    CapabilityTokenRequest,
    CapabilityTokenResponse,
    LoginRequest,
    LogoutRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    RefreshRequest,
    StepUpRequest,
    StepUpResponse,
    TokenResponse,
    TOTPConfirmRequest,
    TOTPEnrolResponse,
)
from core_api.domain.auth import capability, lockout, otp, sessions, totp
from core_api.repo import auth_queries as q
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.scopes import Role, Scope
from sarana_shared.domain.ids import ensure_correlation_id
from sarana_shared.domain.localised import Locale
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import Conflict, Forbidden, Unauthenticated

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _source_hash(request: Request, hasher: KeyedHasherDep) -> str:
    """HMAC of the caller's address, for the per-address backoff.

    Hashed rather than stored: a lockout table holding plaintext addresses would be a
    record of where every officer in the country works from.
    """
    client = request.client
    return hasher.hash(client.host if client else "unknown")


def _assignments(
    assignments: list[object],
) -> list[tuple[Role, ScopeType, str]]:
    """Convert stored role assignments into the tuples the grant expander takes."""
    return [
        (item.role, ScopeType(item.scope_type), item.scope_code)  # type: ignore[attr-defined]
        for item in assignments
    ]


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    tokens: TokensDep,
    passwords: PasswordDep,
    hasher: KeyedHasherDep,
) -> TokenResponse:
    """Email, password and TOTP. Officers, approvers, operators and auditors.

    Every failure returns the same message. Distinguishing "no such account" from "wrong
    password" turns this endpoint into a way of enumerating who works for the state.
    """
    correlation_id = ensure_correlation_id()
    account_hash = hasher.hash(body.email.strip().lower())
    source_hash = _source_hash(request, hasher)

    failures = await q.count_recent_failures(
        session, account_hash=account_hash, window=lockout.ATTEMPT_WINDOW
    )
    locked_until = lockout.next_lock_until(failures)
    if locked_until is not None and locked_until > utc_now():
        raise Unauthenticated(
            "Too many failed attempts. Try again shortly.",
            context={"reason": "locked_out", "failures": failures},
        )

    user = await q.find_user_by_email(session, body.email)
    password_ok = passwords.verify(user.password_hash if user else None, body.password)

    if user is None or not password_ok or user.status != "ACTIVE":
        await q.record_login_attempt(
            session,
            account_hash=account_hash,
            source_hash=source_hash,
            succeeded=False,
            correlation_id=correlation_id,
            failure_reason="BAD_CREDENTIALS",
        )
        raise Unauthenticated("Those details did not match.", context={"reason": "bad_credentials"})

    enrolment = await q.load_mfa_enrolment(session, user.id)
    step_up_at = None
    if enrolment is not None and enrolment.confirmed_at is not None:
        secret = request.app.state.field_cipher.decrypt(
            enrolment.secret_encrypted, context=str(user.id)
        )
        if not body.totp_code or not totp.verify(secret, body.totp_code):
            await q.record_login_attempt(
                session,
                account_hash=account_hash,
                source_hash=source_hash,
                succeeded=False,
                correlation_id=correlation_id,
                failure_reason="BAD_TOTP",
            )
            raise Unauthenticated("Those details did not match.", context={"reason": "bad_totp"})
        step_up_at = utc_now()

    await q.record_login_attempt(
        session,
        account_hash=account_hash,
        source_hash=source_hash,
        succeeded=True,
        correlation_id=correlation_id,
    )

    issued = await _issue_pair(
        session,
        settings=settings,
        tokens=tokens,
        hasher=hasher,
        user_id=user.id,
        device_id=None,
        platform=body.device_platform,
        step_up_at=step_up_at,
        mfa_enrolment_required=enrolment is None or enrolment.confirmed_at is None,
    )
    return issued.response


@dataclass(frozen=True, slots=True)
class IssuedPair:
    """A minted pair, plus the id of the refresh token so rotation can chain to it."""

    response: TokenResponse
    refresh_token_id: UUID


async def _issue_pair(
    session: SessionDep,
    *,
    settings: SettingsDep,
    tokens: TokensDep,
    hasher: KeyedHasherDep,
    user_id: UUID,
    device_id: UUID | None,
    platform: str,
    step_up_at: datetime | None = None,
    family_id: UUID | None = None,
    mfa_enrolment_required: bool = False,
) -> IssuedPair:
    """Mint an access and refresh pair, recording the refresh hash and its device."""
    device = await q.upsert_device(session, user_id=user_id, device_id=device_id, platform=platform)
    refresh = sessions.mint(
        hasher,
        family_id=family_id,
        ttl=timedelta(seconds=settings.refresh_token_ttl_seconds),
    )
    await q.store_refresh_token(
        session,
        token_id=refresh.token_id,
        user_id=user_id,
        device_id=device.id,
        family_id=refresh.family_id,
        token_hash=refresh.token_hash,
        expires_at=refresh.expires_at,
    )

    assignments = await q.load_role_assignments(session, user_id)
    access = tokens.issue(
        str(user_id),
        roles=frozenset(item.role for item in assignments),
        grants=grants_for_assignments(_assignments(list(assignments))),
        device_id=str(device.id),
        step_up_at=step_up_at,
    )

    return IssuedPair(
        response=TokenResponse(
            access_token=access,
            refresh_token=refresh.secret,
            expires_in=settings.access_token_ttl_seconds,
            mfa_enrolment_required=mfa_enrolment_required,
        ),
        refresh_token_id=refresh.token_id,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    session: SessionDep,
    settings: SettingsDep,
    tokens: TokensDep,
    hasher: KeyedHasherDep,
) -> TokenResponse:
    """Exchange a refresh token for a new pair. Single use, rotating.

    Presenting a token that has already been exchanged revokes the whole device family
    and raises a security event. A client retry after a lost response and a stolen copy
    are indistinguishable from here, and only one of them is safe to ignore.
    """
    token_hash = hasher.hash(body.refresh_token)
    stored = await q.find_refresh_token(session, token_hash)
    outcome = sessions.classify(stored)

    if outcome is not sessions.RefreshOutcome.ROTATED:
        if sessions.revokes_family(outcome) and stored is not None:
            revoked = await q.revoke_family(
                session, family_id=stored.family_id, reason="REUSE_DETECTED"
            )
            await q.record_security_event(
                session,
                kind="REFRESH_REUSE",
                subject_id=stored.user_id,
                detail={"sessions_revoked": revoked, "device_bound": True},
            )
            _log.warning(
                "refresh_token_reuse",
                subject_id=str(stored.user_id),
                sessions_revoked=revoked,
            )
        raise Unauthenticated(
            str(sessions.RefreshRejected(outcome)), context={"reason": outcome.value}
        )

    if stored is None:  # unreachable: classify() returns UNKNOWN for a missing row
        raise Unauthenticated(
            str(sessions.RefreshRejected(sessions.RefreshOutcome.UNKNOWN)),
            context={"reason": "unknown"},
        )

    replacement = await _issue_pair(
        session,
        settings=settings,
        tokens=tokens,
        hasher=hasher,
        user_id=stored.user_id,
        device_id=stored.device_id,
        platform="web",
        family_id=stored.family_id,
    )
    # Chain the old token to its replacement. Given a replayed token, an operator can
    # then walk forward to see exactly which sessions descended from it.
    await q.mark_rotated(
        session, token_id=stored.token_id, replacement_id=replacement.refresh_token_id
    )
    return replacement.response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    session: SessionDep,
    hasher: KeyedHasherDep,
) -> Response:
    """End this session, or every session on the device.

    Returns 204 whether or not the token was recognised. Reporting "no such session"
    would let someone probe which tokens are live.
    """
    stored = await q.find_refresh_token(session, hasher.hash(body.refresh_token))
    if stored is not None:
        if body.all_devices:
            await q.revoke_family(session, family_id=stored.family_id, reason="LOGOUT")
        else:
            await q.revoke_device(session, device_id=stored.device_id, reason="LOGOUT")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/otp/request", response_model=OTPRequestResponse)
async def request_otp(
    body: OTPRequest,
    session: SessionDep,
    hasher: KeyedHasherDep,
    settings: SettingsDep,
) -> OTPRequestResponse:
    """Send a citizen a verification code.

    The response is identical whether or not the number is known. Confirming that a
    number is registered would turn this into a way of checking who has reported damage.
    """
    msisdn_hash = hasher.hash(body.msisdn.strip())

    recent = await q.recent_otp_sends(session, msisdn_hash=msisdn_hash, window=otp.SEND_WINDOW)
    otp.assert_can_send(recent)

    generated = otp.generate()
    user = await q.find_user_by_phone_hash(session, msisdn_hash)
    locale = body.locale or Locale.SI

    await q.store_otp_challenge(
        session,
        msisdn_hash=msisdn_hash,
        code_hash=hasher.hash(generated.code),
        language=locale.value,
        expires_at=generated.expires_at,
        max_attempts=otp.MAX_ATTEMPTS,
    )

    # Delivery goes through the mocked telco gateway. There is no live SMS integration.
    _log.info(
        "otp_dispatched",
        channel="SMS",
        language=locale.value,
        known_account=user is not None,
        source="MOCK",
    )

    return OTPRequestResponse(
        expires_in=int(otp.TTL.total_seconds()), attempts_allowed=otp.MAX_ATTEMPTS
    )


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp(
    body: OTPVerifyRequest,
    session: SessionDep,
    settings: SettingsDep,
    tokens: TokensDep,
    hasher: KeyedHasherDep,
) -> TokenResponse:
    """Prove possession of the number and receive a session."""
    msisdn_hash = hasher.hash(body.msisdn.strip())
    challenge = await q.find_live_otp(session, msisdn_hash)

    if challenge is None or otp.is_expired(challenge.expires_at):
        raise Unauthenticated(
            "That code has expired. Request a new one.", context={"reason": "otp_expired"}
        )

    if otp.attempts_remaining(challenge.attempts, challenge.max_attempts) == 0:
        await q.consume_otp_challenge(session, challenge.id)
        raise Unauthenticated(
            "Too many attempts. Request a new code.", context={"reason": "otp_exhausted"}
        )

    if not hasher.matches(body.code.strip(), challenge.code_hash):
        await q.record_otp_attempt(session, challenge.id)
        raise Unauthenticated("That code did not match.", context={"reason": "otp_mismatch"})

    await q.consume_otp_challenge(session, challenge.id)

    user = await q.find_user_by_phone_hash(session, msisdn_hash)
    if user is None:
        raise Unauthenticated("That code did not match.", context={"reason": "otp_no_account"})

    issued = await _issue_pair(
        session,
        settings=settings,
        tokens=tokens,
        hasher=hasher,
        user_id=user.id,
        device_id=None,
        platform=body.device_platform,
    )
    return issued.response


@router.post("/totp/enrol", response_model=TOTPEnrolResponse)
async def enrol_totp(
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    hasher: KeyedHasherDep,
) -> TOTPEnrolResponse:
    """Generate a second factor. Inactive until confirmed.

    The recovery codes are returned exactly once and stored hashed. A GN officer whose
    phone is destroyed in the disaster they are responding to must not be locked out of
    recording assessments.
    """
    enrolment = totp.enrol(principal.subject_id)
    cipher = request.app.state.field_cipher

    await q.upsert_mfa_enrolment(
        session,
        user_id=principal.subject_id,  # type: ignore[arg-type]  # a UUID string from the token
        secret_encrypted=cipher.encrypt(enrolment.secret, context=principal.subject_id),
        recovery_code_hashes=[hasher.hash(code) for code in enrolment.recovery_codes],
    )

    return TOTPEnrolResponse(
        provisioning_uri=enrolment.provisioning_uri,
        recovery_codes=list(enrolment.recovery_codes),
    )


@router.post("/totp/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_totp(
    body: TOTPConfirmRequest,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
) -> Response:
    """Activate an enrolment by producing a code from it."""
    enrolment = await q.load_mfa_enrolment(session, principal.subject_id)  # type: ignore[arg-type]
    if enrolment is None:
        raise Conflict(
            "There is no pending second-factor enrolment for this account.",
            context={"subject_id": principal.subject_id},
        )

    cipher = request.app.state.field_cipher
    secret = cipher.decrypt(enrolment.secret_encrypted, context=principal.subject_id)
    totp.confirm_enrolment(secret, body.code)

    await q.confirm_mfa_enrolment(session, principal.subject_id)  # type: ignore[arg-type]
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/step-up", response_model=StepUpResponse)
async def step_up(
    body: StepUpRequest,
    request: Request,
    principal: PrincipalDep,
    session: SessionDep,
    settings: SettingsDep,
    tokens: TokensDep,
) -> StepUpResponse:
    """Re-prove the second factor, for a human-gated action.

    A valid session is not enough to commit a dispatch or release money. An unattended
    workstation with a live session is the realistic attack on a platform like this, not
    a stolen password, and step-up is what puts the person at the keyboard at the moment
    of authorising the payment.
    """
    enrolment = await q.load_mfa_enrolment(session, principal.subject_id)  # type: ignore[arg-type]
    if enrolment is None or enrolment.confirmed_at is None:
        raise Forbidden(
            "This action needs a second factor. Set one up on your account first.",
            context={"subject_id": principal.subject_id},
        )

    cipher = request.app.state.field_cipher
    secret = cipher.decrypt(enrolment.secret_encrypted, context=principal.subject_id)
    if not totp.verify(secret, body.code):
        _log.warning("step_up_failed", subject_id=principal.subject_id)
        raise Unauthenticated("That code did not match.", context={"reason": "bad_totp_step_up"})

    verified_at = utc_now()
    assignments = await q.load_role_assignments(session, principal.subject_id)  # type: ignore[arg-type]
    access = tokens.issue(
        principal.subject_id,
        roles=frozenset(item.role for item in assignments),
        grants=grants_for_assignments(_assignments(list(assignments))),
        device_id=principal.device_id,
        step_up_at=verified_at,
    )

    return StepUpResponse(
        access_token=access,
        expires_in=settings.access_token_ttl_seconds,
        step_up_expires_in=int(totp.STEP_UP_WINDOW.total_seconds()),
    )


@router.post("/capability-token", response_model=CapabilityTokenResponse)
async def mint_capability_token(
    body: CapabilityTokenRequest,
    principal: PrincipalDep,
    settings: SettingsDep,
    tokens: TokensDep,
) -> CapabilityTokenResponse:
    """Mint the offline token a GN officer carries into the field.

    Seventy-two hours, one GN division, one permission: drafting damage assessments.
    Connectivity is the failure mode this platform exists to survive, so the officer has
    to be able to work without it - and the way to make that safe is not to shorten the
    window but to make the credential capable of almost nothing.

    On reconnect the drafts sync and the token is exchanged for a fresh one.
    """
    if not capability.may_hold_capability(principal.roles):
        raise Forbidden(
            "Offline capability tokens are issued to Grama Niladhari officers only.",
            context={"subject_id": principal.subject_id},
        )

    # The officer must already hold the division they are asking to work offline in.
    # Without this check the token would be a way to grant yourself an area.
    principal.assert_can(Scope.ASSESSMENT_WRITE, body.gn_division_code)

    request_model = capability.CapabilityRequest(
        subject_id=principal.subject_id,
        gn_division_code=body.gn_division_code,
        device_id=body.device_id,
    )

    token = tokens.issue(
        request_model.subject_id,
        roles=frozenset({Role.GN_OFFICER}),
        grants=capability.capability_grants(request_model.gn_division_code),
        kind="capability",
        device_id=request_model.device_id,
    )

    _log.info(
        "capability_token_issued",
        subject_id=principal.subject_id,
        gn_division_code=body.gn_division_code,
        ttl_hours=int(capability.CAPABILITY_TTL.total_seconds() // 3600),
    )

    return CapabilityTokenResponse(
        capability_token=token,
        expires_in=int(capability.CAPABILITY_TTL.total_seconds()),
        gn_division_code=body.gn_division_code,
        permits=sorted(scope.value for scope in capability.CAPABILITY_SCOPES),
    )
