"""Holding a machine credential, and turning it into a bearer token when one is needed.

The counterpart to core-api's `POST /api/v1/auth/token`. A service configures a client id
and secret once and calls `authorization()` whenever it needs a header; this handles
fetching, caching and refreshing the short-lived token underneath.

Four behaviours matter, and each replaces something the old long-lived-token approach got
wrong by construction:

**It refreshes before expiry, not after.** A token fetched with fifteen minutes to live is
renewed with a minute to spare. Waiting for a 401 means every service discovers expiry by
failing a request first, and during a national fan-out that is thousands of failed requests
at the same instant.

**One refresh at a time.** A lock, so a hundred concurrent callers finding an expired token
produce one request to core-api rather than a hundred. Without it, expiry becomes a
self-inflicted thundering herd against the service everything else depends on.

**It never falls back to unauthenticated.** A credential that cannot be obtained raises.
Degrading to an anonymous call would turn an authentication failure into a permissions
failure somewhere further along, which is much harder to diagnose and occasionally
succeeds against an endpoint that should have refused it.

**The secret is never logged.** Not at debug, not in an error, not in a repr.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import httpx
import structlog

from sarana_shared.domain.time import utc_now
from sarana_shared.errors import UpstreamUnavailable

_log = structlog.get_logger(__name__)

TOKEN_PATH: Final = "/api/v1/auth/token"  # noqa: S105 - a URL path, not a credential

# Renew this far before the token actually expires. Long enough to cover a slow round trip
# and clock skew between two containers; short enough not to waste most of the lifetime.
REFRESH_MARGIN: Final = timedelta(seconds=60)

CONNECT_TIMEOUT: Final = 3.0
READ_TIMEOUT: Final = 10.0


class CredentialUnavailable(UpstreamUnavailable):
    """A machine token could not be obtained.

    A `SaranaError` with status 503, so a service that does not catch it returns "upstream
    unavailable" rather than a 500 — and never proceeds unauthenticated.
    """

    slug = "service-credential-unavailable"
    title = "Service credential unavailable"


@dataclass
class _CachedToken:
    """A token and when it stops being usable."""

    value: str
    renew_at: datetime

    def usable(self, now: datetime) -> bool:
        return now < self.renew_at


@dataclass
class ServiceCredentials:
    """A client credential, and the short-lived tokens it produces.

    Construct one per service and share it. It is safe across asyncio tasks: the refresh
    is serialised by a lock, so concurrent callers wait for one fetch rather than starting
    their own.
    """

    base_url: str
    client_id: str
    client_secret: str = field(repr=False)
    scope: str | None = None
    client: httpx.AsyncClient | None = None

    _token: _CachedToken | None = field(default=None, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
            )
            self._owns_client = True

    def __repr__(self) -> str:
        """Never render the secret.

        The dataclass field is `repr=False`, and this is belt and braces: a credential
        object reaches a log line eventually, usually inside an exception somebody pasted
        into a ticket.
        """
        return f"ServiceCredentials(base_url={self.base_url!r}, client_id={self.client_id!r})"

    async def aclose(self) -> None:
        """Close the transport, but only if this object opened it."""
        if self._owns_client and self.client is not None:
            await self.client.aclose()

    async def token(self) -> str:
        """A usable access token, fetching or refreshing if needed."""
        now = utc_now()
        cached = self._token
        if cached is not None and cached.usable(now):
            return cached.value

        async with self._lock:
            # Re-check inside the lock. Everyone who queued behind the winner finds the
            # fresh token here rather than fetching again.
            cached = self._token
            if cached is not None and cached.usable(utc_now()):
                return cached.value
            self._token = await self._fetch()
            return self._token.value

    async def authorization(self) -> dict[str, str]:
        """The Authorization header, ready to merge into a request."""
        return {"Authorization": f"Bearer {await self.token()}"}

    def invalidate(self) -> None:
        """Throw the cached token away.

        Call this on a 401 from a downstream service. The credential may have been
        rotated or revoked under us, and the next call should find out rather than
        re-presenting a token that has already been refused.
        """
        self._token = None

    async def _fetch(self) -> _CachedToken:
        """Ask core-api for a token.

        Raises:
            CredentialUnavailable: for any failure. Never returns a token that might not
                work, and never returns None — a caller that got past this line is
                authenticated.
        """
        assert self.client is not None  # noqa: S101 - set in __post_init__, never None
        payload: dict[str, Any] = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            payload["scope"] = self.scope

        try:
            response = await self.client.post(f"{self.base_url}{TOKEN_PATH}", json=payload)
        except (httpx.TimeoutException, httpx.TransportError) as error:
            _log.warning(
                "service_credential_unreachable",
                client_id=self.client_id,
                error=type(error).__name__,
            )
            raise CredentialUnavailable(
                "core-api could not be reached to obtain a service token."
            ) from error

        if response.status_code == 401:
            # Named separately because the remedy is completely different: this is a
            # rotated, revoked or mistyped credential, not an outage, and it will not fix
            # itself by being retried.
            _log.error(
                "service_credential_rejected",
                client_id=self.client_id,
                hint="the credential is wrong, revoked, or was rotated without this "
                "service being updated",
            )
            raise CredentialUnavailable(f"core-api refused the credential for {self.client_id}.")
        if response.status_code >= 400:
            _log.warning(
                "service_credential_failed",
                client_id=self.client_id,
                status=response.status_code,
            )
            raise CredentialUnavailable(
                f"core-api returned {response.status_code} for a service token request."
            )

        try:
            body = response.json()
            token = str(body["access_token"])
            expires_in = int(body["expires_in"])
        except (ValueError, KeyError, TypeError) as error:
            raise CredentialUnavailable(
                "core-api returned a token response this client cannot read."
            ) from error

        # Never renew *after* expiry. If the lifetime is shorter than the margin, renew at
        # the halfway point instead of computing a moment in the past - which would make
        # every call refetch and hammer core-api.
        lifetime = timedelta(seconds=expires_in)
        margin = REFRESH_MARGIN if lifetime > REFRESH_MARGIN * 2 else lifetime / 2
        renew_at = utc_now() + lifetime - margin

        _log.info(
            "service_token_obtained",
            client_id=self.client_id,
            expires_in=expires_in,
            granted_scope=body.get("scope"),
        )
        return _CachedToken(value=token, renew_at=renew_at)
