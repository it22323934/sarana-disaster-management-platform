"""JWT issue and verify, RS256.

Asymmetric on purpose: core-api holds the private key and is the only issuer; every other
service verifies with the public key alone. A compromised incident-svc cannot mint a token
that releases a disbursement.

Other services verify locally against the JWKS. They do not call core-api per request -
that would put a single point of failure directly in the path of the event this platform
exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, Final, Literal

import jwt
from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.auth.grants import InvalidGrant, ScopeGrant, strip_human_gates
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import Unauthenticated

ALGORITHM: Final = "RS256"

# `capability` is the offline token the Field Companion carries. It is a distinct kind so
# that an endpoint can refuse it outright rather than having to notice its narrow scopes.
TokenKind = Literal["access", "refresh", "capability"]


class TokenClaims(BaseModel):
    """The claim set SARANA issues. Registered claims plus a small private set."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sub: str = Field(description="Principal identifier - officer, citizen or service")
    iss: str
    aud: str
    exp: int
    iat: int
    jti: str

    kind: TokenKind = "access"
    roles: list[str] = Field(default_factory=list)
    # Scope grants as `{resource}:{action}:{scope_type}:{scope_code}`. This is the whole
    # authorisation story; there is no separate permission list to fall out of step.
    grants: list[str] = Field(default_factory=list)
    # Binds the token to one installation. A refresh token presented from a different
    # device is a reuse signal, not a convenience.
    device_id: str | None = None
    # Epoch seconds at which the second factor was last verified. The step-up window is
    # measured from here, not from `iat`.
    step_up_at: int | None = None
    machine: bool = False

    def to_principal(self) -> Principal:
        """Build the object handlers actually depend on.

        Raises:
            Unauthenticated: if a grant in the token is malformed. A token carrying a
                scope this build cannot parse is not partially honoured - it is refused.
        """
        try:
            grants = frozenset(ScopeGrant.parse(value) for value in self.grants)
        except InvalidGrant as exc:
            raise Unauthenticated(
                "Authentication failed.",
                context={"reason": "unparseable_grant", "message": str(exc)},
            ) from exc

        return Principal(
            subject_id=self.sub,
            roles=frozenset(Role(role) for role in self.roles),
            grants=grants,
            token_id=self.jti,
            device_id=self.device_id,
            step_up_at=(
                datetime.fromtimestamp(self.step_up_at, tz=UTC)
                if self.step_up_at is not None
                else None
            ),
            is_machine=self.machine,
            is_offline_capability=self.kind == "capability",
        )


@dataclass(frozen=True, slots=True)
class TokenSettings:
    """Key material and lifetimes. Sourced from each service's settings object."""

    public_key_path: Path
    issuer: str
    audience: str
    private_key_path: Path | None = None
    access_ttl: timedelta = timedelta(minutes=15)
    refresh_ttl: timedelta = timedelta(days=30)
    # A GN officer must be able to work for three days on no connectivity.
    capability_ttl: timedelta = timedelta(hours=72)
    # Tolerance for clock skew between services. Deliberately small.
    leeway: timedelta = timedelta(seconds=30)


class TokenService:
    """Issues and verifies tokens.

    A verifier-only instance is constructed without `private_key_path`; calling `issue`
    on it raises rather than falling back to a symmetric secret.
    """

    def __init__(self, settings: TokenSettings) -> None:
        self._settings = settings

    @cached_property
    def _public_key(self) -> str:
        return self._settings.public_key_path.read_text(encoding="utf-8")

    @cached_property
    def _private_key(self) -> str:
        if self._settings.private_key_path is None:
            raise RuntimeError(
                "this service is configured to verify tokens only; "
                "issuing requires SARANA_JWT_PRIVATE_KEY_PATH"
            )
        return self._settings.private_key_path.read_text(encoding="utf-8")

    def issue(
        self,
        subject_id: str,
        *,
        roles: frozenset[Role] | set[Role],
        grants: frozenset[ScopeGrant],
        kind: TokenKind = "access",
        device_id: str | None = None,
        step_up_at: datetime | None = None,
        machine: bool = False,
        token_id: str | None = None,
    ) -> str:
        """Mint a signed token.

        Grants are supplied by the caller, which has read them from `admin.user_role` -
        they are never taken from a request. The two human-gate permissions are stripped
        from any machine principal here, so no configuration mistake can hand an agent
        the ability to commit a dispatch or release money.
        """
        if machine:
            grants = strip_human_gates(grants)

        now = utc_now()
        ttl = {
            "access": self._settings.access_ttl,
            "refresh": self._settings.refresh_ttl,
            "capability": self._settings.capability_ttl,
        }[kind]

        claims = TokenClaims(
            sub=subject_id,
            iss=self._settings.issuer,
            aud=self._settings.audience,
            iat=int(now.timestamp()),
            exp=int((now + ttl).timestamp()),
            jti=token_id or _new_jti(),
            kind=kind,
            roles=sorted(role.value for role in roles),
            grants=sorted(str(grant) for grant in grants),
            device_id=device_id,
            step_up_at=int(step_up_at.timestamp()) if step_up_at else None,
            machine=machine,
        )
        return jwt.encode(claims.model_dump(mode="json"), self._private_key, algorithm=ALGORITHM)

    def verify(self, token: str, *, expect: TokenKind = "access") -> TokenClaims:
        """Verify a token and return its claims.

        Raises:
            Unauthenticated: for any failure - expired, wrong audience, bad signature,
                wrong kind. The reason reaches the client only in general terms; the
                specific cause goes to the logs keyed by correlation ID.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._public_key,
                algorithms=[ALGORITHM],
                audience=self._settings.audience,
                issuer=self._settings.issuer,
                leeway=self._settings.leeway,
                options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthenticated(
                "Your session has expired. Sign in again.", context={"reason": "expired"}
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise Unauthenticated(
                "Authentication failed.",
                context={"reason": type(exc).__name__, "message": str(exc)},
            ) from exc

        claims = TokenClaims.model_validate(payload)
        if claims.kind != expect:
            raise Unauthenticated(
                "Authentication failed.",
                context={"reason": "wrong_token_kind", "got": claims.kind, "expected": expect},
            )
        return claims

    def principal_from(self, token: str, *, expect: TokenKind = "access") -> Principal:
        """Verify a token and return the principal it describes."""
        return self.verify(token, expect=expect).to_principal()


def _new_jti() -> str:
    """A unique token identifier, used for revocation and for audit correlation."""
    from sarana_shared.domain.ids import uuid7

    return str(uuid7())


def bearer_token(authorization_header: str | None) -> str:
    """Extract the credential from an Authorization header.

    Raises:
        Unauthenticated: if the header is absent or is not a Bearer scheme.
    """
    if not authorization_header:
        raise Unauthenticated(
            "Authentication required.", context={"reason": "missing_authorization_header"}
        )
    scheme, _, credential = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not credential.strip():
        raise Unauthenticated(
            "Authentication required.", context={"reason": "unsupported_auth_scheme"}
        )
    return credential.strip()
