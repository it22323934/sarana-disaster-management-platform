"""JWT encode/decode (RS256) and the claim models every service shares.

This is the local-verification half of docs/build-prompts/05-auth-rbac.md: "Other
services verify tokens locally against the JWKS. They do not call core-api per request —
that is a single point of failure during exactly the event this system is for." The
mint side (login, refresh rotation, offline capability token issuance, TOTP enrolment)
lives in core-api and is file 05's job, not this shared package's.
"""

from __future__ import annotations

import time
from typing import Literal
from uuid import UUID

import jwt
from pydantic import BaseModel, Field

from sarana_shared.auth.scopes import Scope

Role = Literal[
    "CITIZEN",
    "GN_OFFICER",
    "DS_APPROVER",
    "DISTRICT_APPROVER",
    "DMC_OPERATOR",
    "DISPATCHER",
    "AUDITOR",
    "ADMIN",
]


class AccessTokenClaims(BaseModel):
    """The decoded, validated claim set of a SARANA access token. 15-minute TTL per
    file 05; this model doesn't enforce that itself, `decode_access_token` does via
    the standard `exp` claim."""

    sub: UUID  # principal (user) id
    roles: list[Role]
    scopes: list[str]  # raw "resource:action:scope_type:scope_id" strings
    jti: UUID  # token id, for revocation checks
    device_id: str | None = None
    step_up_at: int | None = None  # unix ts of last fresh-TOTP verification, if any
    exp: int
    iat: int

    def parsed_scopes(self) -> list[Scope]:
        return [Scope.parse(s) for s in self.scopes]

    def has_fresh_step_up(self, *, within_seconds: int = 300) -> bool:
        """The two human gates require a TOTP verified in the last 5 minutes — a valid
        session alone is never enough (docs/build-prompts/05-auth-rbac.md, rule 2)."""
        if self.step_up_at is None:
            return False
        return (int(time.time()) - self.step_up_at) <= within_seconds


class TokenError(Exception):
    pass


class ExpiredTokenError(TokenError):
    pass


class InvalidTokenError(TokenError):
    pass


def encode_access_token(
    claims: AccessTokenClaims,
    *,
    private_key_pem: str,
    key_id: str,
    issuer: str = "https://sarana.lk",
    audience: str = "sarana-services",
) -> str:
    payload = claims.model_dump(mode="json")
    payload["iss"] = issuer
    payload["aud"] = audience
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": key_id})


def decode_access_token(
    token: str,
    *,
    public_key_pem: str,
    issuer: str = "https://sarana.lk",
    audience: str = "sarana-services",
) -> AccessTokenClaims:
    try:
        payload = jwt.decode(
            token,
            public_key_pem,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredTokenError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"Invalid access token: {exc}") from exc
    return AccessTokenClaims.model_validate(payload)


class InternalPrincipalClaims(BaseModel):
    """The short-lived (30s TTL) internal JWT the gateway attaches as
    `X-Sarana-Principal` when forwarding a request downstream (file 07). Never
    constructed from client input — always re-minted at the gateway from an already
    -verified AccessTokenClaims."""

    sub: UUID
    roles: list[Role]
    scopes: list[str]
    correlation_id: UUID
    exp: int = Field(default_factory=lambda: int(time.time()) + 30)
    iat: int = Field(default_factory=lambda: int(time.time()))
