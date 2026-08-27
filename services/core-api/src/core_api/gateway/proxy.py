"""Forwarding a request to a downstream service.

Auth is resolved once at the edge and forwarded as a signed internal header, so a
downstream never re-validates a citizen's bearer token and never has to be configured
with the public key rotation schedule. The internal token lives for thirty seconds and
names its target service as the audience: a token captured from an incident-svc call
cannot be replayed against ledger-svc, and cannot be replayed at all a minute later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import jwt
import structlog

from core_api.gateway.breaker import BreakerRegistry, CircuitOpen
from sarana_shared.auth.principal import Principal
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

ALGORITHM: Final = "RS256"

# Thirty seconds is long enough for a slow downstream call and short enough that a
# captured token is worthless before it can be used.
INTERNAL_TOKEN_TTL_SECONDS: Final = 30

CONNECT_TIMEOUT: Final = 3.0
READ_TIMEOUT: Final = 10.0

PRINCIPAL_HEADER: Final = "X-Sarana-Principal"
CORRELATION_HEADER: Final = "X-Correlation-Id"

# Any header in this namespace is minted by the gateway and only by the gateway. Anything
# a client sends with this prefix is stripped at the edge before routing.
SARANA_HEADER_PREFIX: Final = "x-sarana-"

# Hop-by-hop headers must not be forwarded: they describe this connection, not the
# request, and passing them on corrupts the downstream's own framing.
_HOP_BY_HOP: Final = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


class DownstreamUnavailable(Exception):
    """The downstream could not be reached, or refused to answer in time."""

    def __init__(self, service: str, reason: str) -> None:
        super().__init__(f"{service} is unavailable: {reason}")
        self.service = service
        self.reason = reason


class InternalPrincipalMinter:
    """Mints the short-lived internal token the gateway forwards.

    Separate from `TokenService` because the audience differs per call. A single service
    audience is exactly what must not happen here.
    """

    def __init__(self, private_key_path: Path, *, issuer: str) -> None:
        self._private_key_path = private_key_path
        self._issuer = issuer
        self._cached_key: str | None = None

    @property
    def _private_key(self) -> str:
        if self._cached_key is None:
            self._cached_key = self._private_key_path.read_text(encoding="utf-8")
        return self._cached_key

    def mint(self, principal: Principal | None, *, audience: str) -> str | None:
        """A 30-second token naming the principal and the target service.

        Returns None for an anonymous caller. An anonymous request is forwarded with no
        principal header at all, rather than one asserting anonymity - a downstream that
        sees no header treats the caller as unauthenticated, which is the same decision
        made in one fewer place.
        """
        if principal is None:
            return None

        now = utc_now()
        claims: dict[str, Any] = {
            "sub": principal.subject_id,
            "iss": self._issuer,
            "aud": audience,
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + INTERNAL_TOKEN_TTL_SECONDS,
            "roles": sorted(role.value for role in principal.roles),
            "grants": sorted(str(grant) for grant in principal.grants),
            "internal": True,
        }
        return jwt.encode(claims, self._private_key, algorithm=ALGORITHM)


@dataclass(frozen=True, slots=True)
class Downstream:
    """One routable service."""

    name: str
    base_url: str


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    """What came back, reduced to what the gateway needs to relay it."""

    status_code: int
    content: bytes
    headers: dict[str, str]
    media_type: str | None


def strip_client_headers(headers: dict[str, str]) -> dict[str, str]:
    """Remove every header the gateway alone is allowed to set.

    A client that sends `X-Sarana-Principal` is trying to forge an identity. It is dropped
    silently rather than rejected: telling a prober which header name was interesting is
    free help, and the request is perfectly valid once the header is gone.
    """
    return {
        name: value
        for name, value in headers.items()
        if not name.lower().startswith(SARANA_HEADER_PREFIX) and name.lower() not in _HOP_BY_HOP
    }


class ServiceProxy:
    """Forwards requests to downstreams, guarded by a breaker per service."""

    def __init__(
        self,
        *,
        downstreams: dict[str, Downstream],
        minter: InternalPrincipalMinter,
        breakers: BreakerRegistry,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._downstreams = downstreams
        self._minter = minter
        self._breakers = breakers
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
        )

    @property
    def breakers(self) -> BreakerRegistry:
        return self._breakers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forward(
        self,
        *,
        service: str,
        method: str,
        path: str,
        principal: Principal | None,
        correlation_id: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
    ) -> ProxyResponse:
        """Send one request downstream.

        Raises:
            DownstreamUnavailable: on timeout, connection failure, or an open circuit.
        """
        target = self._downstreams.get(service)
        if target is None:
            raise DownstreamUnavailable(service, "no such downstream is configured")

        breaker = self._breakers.get(service)
        try:
            await breaker.before_call()
        except CircuitOpen as exc:
            raise DownstreamUnavailable(service, str(exc)) from exc

        forwarded = strip_client_headers(dict(headers or {}))
        forwarded[CORRELATION_HEADER] = correlation_id
        internal_token = self._minter.mint(principal, audience=service)
        if internal_token is not None:
            forwarded[PRINCIPAL_HEADER] = internal_token

        url = f"{target.base_url.rstrip('/')}/{path.lstrip('/')}"

        try:
            response = await self._client.request(
                method,
                url,
                headers=forwarded,
                params=params,
                content=content,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            await breaker.record_failure()
            _log.warning(
                "downstream_call_failed",
                downstream=service,
                error=type(error).__name__,
                correlation_id=correlation_id,
            )
            raise DownstreamUnavailable(service, type(error).__name__) from error

        # A 5xx is the downstream telling us it is unwell, so it counts toward the
        # breaker. A 4xx is the caller's problem and says nothing about its health.
        if response.status_code >= 500:
            await breaker.record_failure()
        else:
            await breaker.record_success()

        return ProxyResponse(
            status_code=response.status_code,
            content=response.content,
            headers={
                name: value
                for name, value in response.headers.items()
                if name.lower() not in _HOP_BY_HOP
            },
            media_type=response.headers.get("content-type"),
        )
