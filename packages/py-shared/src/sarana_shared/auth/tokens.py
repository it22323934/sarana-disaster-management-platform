"""JWT issue and verify, RS256.

Asymmetric on purpose: core-api holds the private key and is the only issuer; every
other service verifies with the public key alone. A compromised incident-svc cannot mint
a token that releases a disbursement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, Final, Literal

import jwt
from pydantic import BaseModel, ConfigDict, Field

from sarana_shared.auth.scopes import AreaScope, Principal, Role, Scope, scopes_for_roles
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import Unauthenticated

ALGORITHM: Final = "RS256"

TokenKind = Literal["access", "refresh"]


class TokenClaims(BaseModel):
    """The claim set SARANA issues. Registered claims plus a small private set."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    sub: str = Field(description="Principal identifier - officer ID, citizen ID or service name")
    iss: str
    aud: str
    exp: int
    iat: int
    jti: str

    kind: TokenKind = "access"
    roles: list[str] = Field(default_factory=list)
    # Area codes the principal may act within. `["LK"]` is national.
    areas: list[str] = Field(default_factory=list)
    # Denormalised for cheap verification. Always re-derived from roles on issue, so a
    # role definition change takes effect on the next token rather than needing a purge.
    scopes: list[str] = Field(default_factory=list)
    machine: bool = False

    def to_principal(self) -> Principal:
        """Build the object handlers actually depend on."""
        roles = frozenset(Role(role) for role in self.roles)
        return Principal(
            subject_id=self.sub,
            roles=roles,
            scopes=frozenset(Scope(scope) for scope in self.scopes),
            area=AreaScope(codes=frozenset(self.areas)),
            is_machine=self.machine,
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
        roles: frozenset[Role] | set[Role],
        areas: frozenset[str] | set[str],
        *,
        kind: TokenKind = "access",
        machine: bool = False,
        extra_scopes: frozenset[Scope] | None = None,
    ) -> str:
        """Mint a signed token.

        Scopes are derived from roles, never accepted from a caller. `extra_scopes` may
        only narrow or add non-gate scopes: the two human-gate scopes are stripped from
        any machine principal here, so no configuration mistake can grant them.
        """
        from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES

        now = utc_now()
        ttl = self._settings.access_ttl if kind == "access" else self._settings.refresh_ttl

        granted = scopes_for_roles(frozenset(roles))
        if extra_scopes:
            granted = granted | extra_scopes
        if machine:
            granted = granted - HUMAN_GATE_SCOPES

        claims = TokenClaims(
            sub=subject_id,
            iss=self._settings.issuer,
            aud=self._settings.audience,
            iat=int(now.timestamp()),
            exp=int((now + ttl).timestamp()),
            jti=_new_jti(),
            kind=kind,
            roles=sorted(role.value for role in roles),
            areas=sorted(areas),
            scopes=sorted(scope.value for scope in granted),
            machine=machine,
        )
        return jwt.encode(claims.model_dump(mode="json"), self._private_key, algorithm=ALGORITHM)

    def verify(self, token: str, *, expect: TokenKind = "access") -> TokenClaims:
        """Verify a token and return its claims.

        Raises:
            Unauthenticated: for any failure - expired, wrong audience, bad signature,
                wrong kind. The reason reaches the client only in general terms; the
                specific cause goes to the logs.
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

    def principal_from(self, token: str) -> Principal:
        """Verify an access token and return the principal it describes."""
        return self.verify(token, expect="access").to_principal()


def _new_jti() -> str:
    """A unique token identifier, used for refresh-token revocation lists."""
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
