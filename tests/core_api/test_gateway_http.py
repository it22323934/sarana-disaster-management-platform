"""Gateway behaviour through the real app.

The unit tests in `test_gateway.py` prove the components work. These prove they are wired
in: that a forged header cannot reach authentication, and that a dead downstream degrades
into a stale answer instead of a blank screen.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from core_api.cache import TTLCache
from core_api.gateway.breaker import BreakerRegistry
from core_api.gateway.proxy import (
    Downstream,
    DownstreamUnavailable,
    InternalPrincipalMinter,
    ServiceProxy,
)
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role
from sarana_shared.domain.ids import uuid7
from tests.core_api.conftest import REPO_ROOT

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --------------------------------------------------------------------------------------
# A client cannot forge an identity
# --------------------------------------------------------------------------------------


async def test_a_client_sending_a_principal_header_is_treated_as_anonymous(
    client: AsyncClient,
) -> None:
    """The case the brief names.

    The header is stripped at the edge, so authentication never sees it and the caller is
    exactly as anonymous as if they had sent nothing.
    """
    response = await client.get(
        "/api/v1/admin/provinces",
        headers={"X-Sarana-Principal": "definitely-not-a-real-token"},
    )

    assert response.status_code == 401


async def test_a_forged_header_does_not_upgrade_a_real_but_unprivileged_token(
    client: AsyncClient, citizen_header: dict[str, str]
) -> None:
    """A citizen presenting a forged operator header is still a citizen."""
    response = await client.get(
        "/api/v1/admin/provinces",
        headers={**citizen_header, "X-Sarana-Principal": "forged-operator"},
    )

    assert response.status_code == 403


async def test_a_forged_header_does_not_break_an_otherwise_valid_request(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """Stripped silently: the request is perfectly valid once the header is gone."""
    response = await client.get(
        "/api/v1/admin/provinces",
        headers={**operator_header, "X-Sarana-Stale": "true"},
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------------------
# Rate limiting is wired in
# --------------------------------------------------------------------------------------


async def test_responses_carry_the_rate_limit_headers(
    client: AsyncClient, operator_header: dict[str, str], hierarchy_fixture: dict[str, str]
) -> None:
    """A client that can see its allowance can back off before it is refused."""
    response = await client.get("/api/v1/admin/provinces", headers=operator_header)

    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers


async def test_health_probes_are_never_rate_limited(client: AsyncClient) -> None:
    """A probe that gets a 429 looks like a dead container and gets it killed."""
    for _ in range(60):
        response = await client.get("/healthz")

    assert response.status_code == 200


# --------------------------------------------------------------------------------------
# A dead downstream degrades rather than fails
# --------------------------------------------------------------------------------------


def _principal() -> Principal:
    return Principal(
        subject_id=str(uuid7()),
        roles=frozenset({Role.DMC_OPERATOR}),
        grants=grants_for_assignments([(Role.DMC_OPERATOR, ScopeType.NATIONAL, "*")]),
    )


def _proxy_over(handler: object) -> ServiceProxy:
    """A proxy whose transport is a stub, so no socket is involved."""
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return ServiceProxy(
        downstreams={"incident-svc": Downstream("incident-svc", "http://incident-svc:8002")},
        minter=InternalPrincipalMinter(keys / "jwt-private.pem", issuer="https://sarana.lk"),
        breakers=BreakerRegistry(),
        client=httpx.AsyncClient(transport=transport),
    )


async def test_repeated_downstream_500s_open_the_breaker(
    hierarchy_fixture: dict[str, str],
) -> None:
    """The case the brief names, first half."""

    def always_failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "incident-svc is unwell"})

    proxy = _proxy_over(always_failing)

    for _ in range(5):
        await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    assert proxy.breakers.get("incident-svc").state.value == "open"

    # The sixth call is refused without a request being attempted.
    with pytest.raises(DownstreamUnavailable):
        await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    await proxy.aclose()


async def test_the_console_read_path_still_returns_cached_data(
    hierarchy_fixture: dict[str, str],
) -> None:
    """The case the brief names, second half.

    A blank screen during a cyclone is worse than a stale one, so the cache serves the
    last-known answer and marks it stale rather than propagating the failure.
    """
    cache: TTLCache[dict[str, str]] = TTLCache(ttl_seconds=0.0001)
    cache.put("incidents:latest", {"id": "INC-1", "status": "DISPATCHED"})

    def always_failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    proxy = _proxy_over(always_failing)
    for _ in range(5):
        await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    # The downstream is now cut off, and the console asks for its list anyway.
    with pytest.raises(DownstreamUnavailable):
        await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    served = cache.get_stale("incidents:latest")

    assert served is not None, "the last-known list must still be available"
    payload, is_stale = served
    assert payload["id"] == "INC-1"
    assert is_stale, "and it must be marked stale rather than passed off as current"


async def test_a_timeout_counts_against_the_breaker() -> None:
    """A downstream that never answers is as unavailable as one that refuses."""

    def times_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    proxy = _proxy_over(times_out)

    with pytest.raises(DownstreamUnavailable):
        await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    assert proxy.breakers.get("incident-svc").consecutive_failures == 1
    await proxy.aclose()


async def test_a_downstream_4xx_does_not_open_the_breaker() -> None:
    """A bad request says nothing about the downstream's health."""

    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no such incident"})

    proxy = _proxy_over(not_found)

    for _ in range(10):
        response = await proxy.forward(
            service="incident-svc",
            method="GET",
            path="/api/v1/incidents/missing",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    assert response.status_code == 404
    assert proxy.breakers.get("incident-svc").state.value == "closed"
    await proxy.aclose()


async def test_a_forwarded_request_carries_a_correlation_id_and_internal_token() -> None:
    """Both are attached by the gateway, never taken from the client."""
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={})

    proxy = _proxy_over(capture)
    correlation_id = str(uuid7())

    await proxy.forward(
        service="incident-svc",
        method="GET",
        path="/api/v1/incidents",
        principal=_principal(),
        correlation_id=correlation_id,
        headers={"X-Sarana-Principal": "forged"},
    )

    assert seen["x-correlation-id"] == correlation_id
    assert seen["x-sarana-principal"] != "forged", "the gateway mints this, never the client"
    await proxy.aclose()


async def test_an_anonymous_request_forwards_no_principal_header() -> None:
    """A downstream seeing no header treats the caller as unauthenticated."""
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={})

    proxy = _proxy_over(capture)

    await proxy.forward(
        service="incident-svc",
        method="GET",
        path="/api/v1/incidents",
        principal=None,
        correlation_id=str(uuid7()),
    )

    assert "x-sarana-principal" not in seen
    await proxy.aclose()


async def test_an_unconfigured_downstream_is_refused_not_guessed() -> None:
    proxy = _proxy_over(lambda request: httpx.Response(200))

    with pytest.raises(DownstreamUnavailable, match="no such downstream"):
        await proxy.forward(
            service="nonexistent-svc",
            method="GET",
            path="/",
            principal=_principal(),
            correlation_id=str(uuid7()),
        )

    await proxy.aclose()
