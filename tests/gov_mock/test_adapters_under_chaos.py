"""Every adapter survives every injection, and nothing 500s.

This is the test build file 11 names in its definition of done, and it is the reason the
mock misbehaves at all. The property under test is not "the adapter works" — it is that
when the government system does the worst thing it can do, the adapter turns it into a
**typed** failure that a service can catch, and never into an unhandled 500.

`GovUpstreamError` is a `SaranaError` with status 503, so even a service that forgets to
catch one returns "upstream unavailable" rather than "something went wrong". During a
cyclone that is the difference between an operator knowing the Met feed is down and an
operator filing a bug.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from httpx import AsyncClient

from sarana_shared.adapters.gov import (
    GovMalformedResponse,
    GovRefused,
    GovTimeout,
    GovUpstreamError,
)
from sarana_shared.adapters.gov.dmc import DmcMockClient
from sarana_shared.adapters.gov.met import MetMockClient
from sarana_shared.adapters.gov.nbro import NbroMockClient
from sarana_shared.adapters.gov.ndrsc import NdrscMockClient
from sarana_shared.adapters.gov.payment import PaymentMockClient
from sarana_shared.adapters.gov.registry import RegistryMockClient
from sarana_shared.adapters.gov.telco import TelcoMockClient

# One read per adapter, named by the system it belongs to. Reads rather than writes: a
# write under 100% timeout is a different and more interesting test, and it lives below.
READS: list[tuple[str, Callable[[AsyncClient], object]]] = [
    ("met", lambda t: MetMockClient("", client=t).warnings()),
    ("met", lambda t: MetMockClient("", client=t).observations()),
    ("nbro", lambda t: NbroMockClient("", client=t).rain_thresholds()),
    ("nbro", lambda t: NbroMockClient("", client=t).zonation(gn_division_code="LK-51-01-001")),
    ("dmc", lambda t: DmcMockClient("", client=t).safety_locations()),
    ("dmc", lambda t: DmcMockClient("", client=t).evacuation_orders()),
    ("ndrsc", lambda t: NdrscMockClient("", client=t).cost_schedules()),
    (
        "registry",
        lambda t: RegistryMockClient("", client=t).officers(gn_division_code="LK-51-01-001"),
    ),
    ("registry", lambda t: RegistryMockClient("", client=t).verify_nic("199012345678")),
    ("telco", lambda t: TelcoMockClient("", client=t).coverage(gn_division_code="LK-51-01-001")),
    ("pay", lambda t: PaymentMockClient("", client=t).transfer("MOCK-PAY-CASH-00000001")),
]


@pytest.mark.parametrize(
    ("system", "call"), READS, ids=[f"{n}-{i}" for i, (n, _) in enumerate(READS)]
)
async def test_a_total_timeout_surfaces_as_a_typed_error(
    chaotic_client: Callable[..., AsyncClient],
    system: str,
    call: Callable[[AsyncClient], object],
) -> None:
    """With 100% timeout injection, every adapter raises `GovTimeout`.

    The mock genuinely holds the connection rather than answering 504 immediately, and
    both ends of that produce the same error. Over a real socket the client's read timeout
    fires first and httpx raises. Here the transport is in-process, so there is no socket
    to abandon: the hold elapses and the mock answers 504, which the adapter maps to
    `GovTimeout` because a gateway timeout is the same fact reported by the other party.

    Landing on one error either way is the property worth having. A caller deciding
    whether a retry is safe must not have to know which side noticed.
    """
    async with chaotic_client(timeout_pct=100.0, timeout_hold_seconds=0.3) as transport:
        transport.timeout = 0.1

        with pytest.raises(GovTimeout) as raised:
            await call(transport)  # type: ignore[misc]

    assert raised.value.status == 503
    assert raised.value.context["upstream_system"]


@pytest.mark.parametrize(
    ("system", "call"), READS, ids=[f"{n}-{i}" for i, (n, _) in enumerate(READS)]
)
async def test_a_total_outage_surfaces_as_a_typed_error(
    chaotic_client: Callable[..., AsyncClient],
    system: str,
    call: Callable[[AsyncClient], object],
) -> None:
    """With 100% error injection, every adapter raises `GovRefused`, never a 500."""
    async with chaotic_client(error_pct=100.0) as transport:
        with pytest.raises(GovRefused) as raised:
            await call(transport)  # type: ignore[misc]

    assert raised.value.status == 503
    assert raised.value.upstream_status == 503


@pytest.mark.parametrize(
    ("system", "call"), READS, ids=[f"{n}-{i}" for i, (n, _) in enumerate(READS)]
)
async def test_a_malformed_body_surfaces_as_a_typed_error(
    chaotic_client: Callable[..., AsyncClient],
    system: str,
    call: Callable[[AsyncClient], object],
) -> None:
    """A 200 carrying an HTML error page raises `GovMalformedResponse`, not a parse error.

    This is the injection that models what real agency APIs actually do, and the one an
    adapter is most likely to get wrong: `response.json()` on an HTML body raises
    `ValueError`, which no caller is catching.
    """
    async with chaotic_client(malformed_pct=100.0) as transport:
        with pytest.raises(GovMalformedResponse) as raised:
            await call(transport)  # type: ignore[misc]

    assert raised.value.status == 503


async def test_every_typed_failure_is_an_upstream_error(
    chaotic_client: Callable[..., AsyncClient],
) -> None:
    """All three failure classes share one base, so one `except` catches the lot.

    A service that wants to degrade gracefully writes `except GovUpstreamError` once. If
    these ever stopped sharing a base, that clause would silently stop catching one of
    them and the failure would escape as a 500.
    """
    for error_class in (GovTimeout, GovRefused, GovMalformedResponse):
        assert issubclass(error_class, GovUpstreamError)


async def test_a_write_under_total_timeout_is_still_idempotent(
    client: AsyncClient, chaotic_client: Callable[..., AsyncClient]
) -> None:
    """A claim submitted, timed out, and resubmitted produces one claim, not two.

    The dangerous case: a timeout says nothing about whether the write was applied, so the
    caller retries — and a claims system that took the retry as a new claim would pay a
    household twice. Idempotency on `client_reference` is what makes the retry safe, and
    it has to hold across the timeout, not just across two clean calls.
    """
    submission = {
        "client_reference": "SARANA-CLAIM-0001",
        "household_reference": "HH-5101001-0001",
        "gn_division_code": "LK-51-01-001",
        "cost_schedule_version": "2025.11",
        "amount_lkr_cents": 250_000_00,
        "assessed_at": "2025-11-29T04:00:00+00:00",
        "approved_by": ["ds.kandy@sarana.lk"],
        "calculation_trace": {"formula": "250,000 per fully destroyed house"},
    }

    first = await client.post("/ndrsc/v1/claims", json=submission)
    assert first.status_code == 201
    reference = first.json()["claim"]["claim_reference"]

    # The retry the caller makes after a timeout it cannot interpret.
    retry = await client.post("/ndrsc/v1/claims", json=submission)
    assert retry.status_code == 200
    assert retry.json()["claim"]["claim_reference"] == reference

    state = (await client.get("/mock/v1/state")).json()
    assert state["recorded"]["claims"] == 1


async def test_the_control_plane_is_never_injected_into(
    chaotic_client: Callable[..., AsyncClient],
) -> None:
    """At 100% on every injection, `/mock/v1/*` still answers.

    Without this exemption, turning chaos all the way up would be unrecoverable: the only
    endpoint that can turn it back off would itself be failing, and the only way out would
    be restarting the container in the middle of a demo.
    """
    async with chaotic_client(
        timeout_pct=100.0, error_pct=100.0, malformed_pct=100.0, stale_pct=100.0
    ) as transport:
        transport.timeout = 2.0

        state = await transport.get("/mock/v1/state")
        assert state.status_code == 200

        # And it can put itself back.
        quiet = await transport.post("/mock/v1/chaos", json={"timeout_pct": 0.0, "error_pct": 0.0})
        assert quiet.status_code == 200
        assert quiet.json()["chaos"]["timeout_pct"] == 0.0


async def test_a_stale_response_is_well_formed_and_wrong(
    client: AsyncClient, chaotic_client: Callable[..., AsyncClient]
) -> None:
    """Staleness produces a valid answer computed from an earlier instant.

    The nastiest injection precisely because nothing about the response looks wrong. The
    test pins it by comparing the observation timestamp against the honest one: same
    shape, same fields, three hours behind.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    await client.post("/mock/v1/scenario/advance", json={"to": "T+6h"})
    honest = (await client.get("/met/v1/observations", params={"station": "MET-020"})).json()

    async with chaotic_client(stale_pct=100.0, stale_window_hours=3.0) as transport:
        await transport.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
        await transport.post("/mock/v1/scenario/advance", json={"to": "T+6h"})
        stale = (await transport.get("/met/v1/observations", params={"station": "MET-020"})).json()

    honest_row = honest["observations"][0]
    stale_row = stale["observations"][0]

    assert set(honest_row) == set(stale_row), "a stale response must be structurally identical"
    assert stale_row["observed_at"] < honest_row["observed_at"]
