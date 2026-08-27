"""The gateway: header hygiene, circuit breaking and rate limits.

These are unit tests over the components. The header-stripping rule is also tested through
the real app in `test_core_api_http.py`, because the thing that matters is not that the
function works but that nothing can reach authentication with a forged header.
"""

from __future__ import annotations

import pytest

from core_api.gateway.breaker import (
    CircuitBreaker,
    CircuitOpen,
    BreakerRegistry,
    BreakerState,
)
from core_api.gateway.proxy import strip_client_headers
from core_api.gateway.ratelimit import (
    ANONYMOUS_LIMIT,
    CITIZEN_LIMIT,
    OFFICER_LIMIT,
    OPERATOR_LIMIT,
    RateLimiter,
    bucket_key,
    limit_for,
)
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Role
from sarana_shared.domain.ids import uuid7

# Only the breaker tests are async, so the mark is applied per test rather than to the
# module - a module-level mark on a sync test is a warning on every run.
asyncio_test = pytest.mark.asyncio(loop_scope="session")


def principal_with(role: Role) -> Principal:
    return Principal(
        subject_id=str(uuid7()),
        roles=frozenset({role}),
        grants=grants_for_assignments([(role, ScopeType.NATIONAL, "*")]),
    )


# --------------------------------------------------------------------------------------
# Header stripping
# --------------------------------------------------------------------------------------


def test_a_client_supplied_principal_header_is_removed() -> None:
    """The header carries identity. A client setting one is forging it."""
    cleaned = strip_client_headers(
        {"X-Sarana-Principal": "forged", "Accept": "application/json"}
    )

    assert "X-Sarana-Principal" not in cleaned
    assert cleaned["Accept"] == "application/json"


def test_stripping_is_case_insensitive() -> None:
    """HTTP header names are case-insensitive, so the check must be too."""
    cleaned = strip_client_headers({"x-SARANA-Principal": "forged"})

    assert cleaned == {}


def test_every_header_in_the_sarana_namespace_is_removed() -> None:
    """The whole prefix is reserved, not just the one header that carries identity."""
    cleaned = strip_client_headers(
        {"X-Sarana-Stale": "true", "X-Sarana-Cache": "hit", "X-Sarana-Anything": "1"}
    )

    assert cleaned == {}


def test_hop_by_hop_headers_are_not_forwarded() -> None:
    """They describe this connection, not the request."""
    cleaned = strip_client_headers(
        {"Connection": "keep-alive", "Transfer-Encoding": "chunked", "Accept": "*/*"}
    )

    assert set(cleaned) == {"Accept"}


# --------------------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------------------


@asyncio_test
async def test_the_breaker_opens_after_five_consecutive_failures() -> None:
    breaker = CircuitBreaker(name="incident-svc")

    for _ in range(5):
        await breaker.before_call()
        await breaker.record_failure()

    assert breaker.state is BreakerState.OPEN


@asyncio_test
async def test_an_open_breaker_refuses_without_attempting_the_call() -> None:
    """The point is to stop spending the pool on calls that are going to fail."""
    breaker = CircuitBreaker(name="incident-svc")
    for _ in range(5):
        await breaker.before_call()
        await breaker.record_failure()

    with pytest.raises(CircuitOpen) as caught:
        await breaker.before_call()

    assert caught.value.retry_after > 0


@asyncio_test
async def test_a_success_resets_the_failure_count() -> None:
    """Four failures and a success is not five failures."""
    breaker = CircuitBreaker(name="incident-svc")
    for _ in range(4):
        await breaker.before_call()
        await breaker.record_failure()

    await breaker.before_call()
    await breaker.record_success()

    assert breaker.consecutive_failures == 0
    assert breaker.state is BreakerState.CLOSED


@asyncio_test
async def test_half_open_admits_exactly_one_probe() -> None:
    """Letting the full load back at once is how a recovering service is re-killed."""
    breaker = CircuitBreaker(name="incident-svc", recovery_seconds=0.0)
    for _ in range(5):
        await breaker.before_call()
        await breaker.record_failure()

    # Recovery window has already elapsed, so the first call becomes the probe.
    await breaker.before_call()
    assert breaker.state is BreakerState.HALF_OPEN

    with pytest.raises(CircuitOpen):
        await breaker.before_call()


@asyncio_test
async def test_a_failed_probe_reopens_immediately() -> None:
    """The probe existed to answer exactly that question; it does not get four more."""
    breaker = CircuitBreaker(name="incident-svc", recovery_seconds=0.0)
    for _ in range(5):
        await breaker.before_call()
        await breaker.record_failure()

    await breaker.before_call()
    await breaker.record_failure()

    assert breaker.state is BreakerState.OPEN


@asyncio_test
async def test_a_successful_probe_closes_the_circuit() -> None:
    breaker = CircuitBreaker(name="incident-svc", recovery_seconds=0.0)
    for _ in range(5):
        await breaker.before_call()
        await breaker.record_failure()

    await breaker.before_call()
    await breaker.record_success()

    assert breaker.state is BreakerState.CLOSED


def test_the_registry_reports_every_breaker_state() -> None:
    """/readyz and the console both need to see which downstreams are cut off."""
    registry = BreakerRegistry()
    registry.get("incident-svc")
    registry.get("ledger-svc")

    assert registry.states() == {"incident-svc": "closed", "ledger-svc": "closed"}


# --------------------------------------------------------------------------------------
# Rate limits
# --------------------------------------------------------------------------------------


def test_each_kind_of_caller_gets_the_documented_allowance() -> None:
    assert limit_for(None) == ANONYMOUS_LIMIT
    assert limit_for(principal_with(Role.CITIZEN)) == CITIZEN_LIMIT
    assert limit_for(principal_with(Role.GN_OFFICER)) == OFFICER_LIMIT
    assert limit_for(principal_with(Role.DMC_OPERATOR)) == OPERATOR_LIMIT


def test_an_authenticated_caller_is_counted_by_subject_not_address() -> None:
    """Moving between devices or networks must not reset the allowance."""
    principal = principal_with(Role.CITIZEN)

    assert bucket_key(principal, "1.2.3.4") == bucket_key(principal, "5.6.7.8")


def test_anonymous_callers_are_counted_per_address() -> None:
    assert bucket_key(None, "1.2.3.4") != bucket_key(None, "5.6.7.8")


def test_a_caller_within_its_allowance_is_permitted() -> None:
    limiter = RateLimiter()

    for _ in range(CITIZEN_LIMIT):
        decision = limiter.check("sub:someone", CITIZEN_LIMIT)

    assert decision.allowed
    assert decision.remaining == 0


def test_the_request_past_the_allowance_is_refused_with_a_retry_after() -> None:
    limiter = RateLimiter()
    for _ in range(CITIZEN_LIMIT):
        limiter.check("sub:someone", CITIZEN_LIMIT)

    decision = limiter.check("sub:someone", CITIZEN_LIMIT)

    assert not decision.allowed
    assert decision.retry_after >= 1


def test_one_caller_hitting_its_limit_does_not_affect_another() -> None:
    """A single runaway client must not throttle everyone else."""
    limiter = RateLimiter()
    for _ in range(CITIZEN_LIMIT + 5):
        limiter.check("sub:noisy", CITIZEN_LIMIT)

    assert limiter.check("sub:quiet", CITIZEN_LIMIT).allowed


def test_the_bucket_store_is_bounded() -> None:
    """An unbounded counter store is a memory leak waiting for a busy day."""
    limiter = RateLimiter(max_buckets=10)

    for index in range(100):
        limiter.check(f"ip:10.0.0.{index}", ANONYMOUS_LIMIT)

    assert limiter.check("ip:10.0.0.99", ANONYMOUS_LIMIT).allowed
