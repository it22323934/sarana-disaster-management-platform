"""The two mocks whose failure modes the platform has to handle, not avoid.

**Payments fail after acceptance.** Roughly three in a hundred, and always after the ledger
has already recorded a release. The ledger is append-only, so the correction is a
compensating entry plus a grievance raised on the household's behalf — never a silent
retry, which would leave a household with a published disbursement and an empty account.

  What is tested here is the mock's half: a transfer that fails does so with a reason
  specific enough to put in front of a household, it is distinguishable from one that is
  merely still in flight, and the fate is stable across polls. Wiring `ledger-svc` to raise
  the compensating entry is not built and is recorded as a gap in HANDOFF.md; a test
  asserting it today would be asserting nothing.

**Registries have gaps.** Roughly one well-formed NIC in twelve does not resolve, and that
is a fact about the register rather than about the person. A household that cannot be
verified needs a manual check, never exclusion from an aid list.
"""

from __future__ import annotations

from httpx import AsyncClient

from gov_mock.data.registry import NOT_FOUND_SHARE, generate_nic


def _transfer(reference: str, **overrides: object) -> dict[str, object]:
    return {
        "client_reference": reference,
        "amount_lkr_cents": 250_000_00,
        "rail": "MOBILE_MONEY",
        "beneficiary_ref_hash": "a" * 64,
        "narrative": "Disaster relief",
        **overrides,
    }


async def _find_failing_reference(client: AsyncClient) -> str:
    """A transfer the rail will fail. Fate is derived from the reference, so this is stable.

    Every transfer is submitted *before* the clock moves, then time is advanced once. A
    transfer submitted after the advance would have no elapsed settlement window and would
    read as ACCEPTED forever, which is a property of this mock worth knowing: settlement is
    measured in simulated time, and the clock only moves when somebody moves it.
    """
    references = []
    for index in range(200):
        response = await client.post("/pay/v1/transfers", json=_transfer(f"SARANA-PAY-{index:04d}"))
        references.append(response.json()["transfer"]["transfer_ref"])

    await client.post("/mock/v1/scenario/advance", json={"to": "T+24h"})

    for reference in references:
        state = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]
        if state["state"] == "FAILED":
            return reference
    raise AssertionError(
        f"no failing transfer in {len(references)}; expected about "
        f"{len(references) * 0.03:.0f} at a 3% failure rate"
    )


async def test_a_transfer_is_accepted_before_it_settles(client: AsyncClient) -> None:
    """Acceptance is not settlement, and the two must not be confused.

    Anything that reports an accepted transfer to a household as a completed payment is
    lying to somebody waiting for money.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})

    response = await client.post("/pay/v1/transfers", json=_transfer("SARANA-PAY-ACCEPT"))

    assert response.status_code == 201
    body = response.json()["transfer"]
    assert body["state"] == "ACCEPTED"
    assert body["settled_at"] is None


async def test_settlement_needs_time_to_pass(client: AsyncClient) -> None:
    """A transfer settles only once the rail's settlement window has elapsed.

    The clock is pinned, so a demo has to advance it explicitly to watch money arrive.
    That is the right shape: it makes the window between the ledger releasing a payment
    and the household having it visible rather than instantaneous.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    created = await client.post("/pay/v1/transfers", json=_transfer("SARANA-PAY-SETTLE"))
    reference = created.json()["transfer"]["transfer_ref"]

    before = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]
    assert before["state"] == "ACCEPTED"

    await client.post("/mock/v1/scenario/advance", json={"to": "T-24h"})
    after = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]
    assert after["state"] in {"SETTLED", "FAILED"}


async def test_a_failed_transfer_names_a_reason_a_household_can_act_on(
    client: AsyncClient,
) -> None:
    """A failure carries a specific reason, not "payment failed".

    Each reason has a different remedy — a closed account, a dormant one, a name that does
    not match — and the grievance raised for the household should say which one applies.
    "Payment failed" tells a family nothing they can do.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    reference = await _find_failing_reference(client)

    failed = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]

    assert failed["state"] == "FAILED"
    assert failed["failure_reason"] in {
        "ACCOUNT_CLOSED",
        "ACCOUNT_DORMANT",
        "NAME_MISMATCH",
        "INVALID_ACCOUNT",
        "LIMIT_EXCEEDED",
    }
    # No settlement instant on a failure. A ledger reading `settled_at` to decide whether
    # money moved must not find one here.
    assert failed["settled_at"] is None


async def test_a_transfers_fate_does_not_change_between_polls(client: AsyncClient) -> None:
    """Polling a transfer twice gives the same answer.

    A mock that re-rolled on each poll would show transfers recovering from FAILED, which
    no rail does and no caller should be written to expect.
    """
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})
    reference = await _find_failing_reference(client)

    first = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]
    second = (await client.get(f"/pay/v1/transfers/{reference}")).json()["transfer"]

    assert first == second


async def test_resubmitting_a_reference_returns_the_same_transfer(client: AsyncClient) -> None:
    """Idempotent on `client_reference`, so a retry after a timeout cannot pay twice."""
    await client.post("/mock/v1/scenario/load", json={"scenario_id": "ditwah_kandy"})

    first = await client.post("/pay/v1/transfers", json=_transfer("SARANA-PAY-IDEM"))
    second = await client.post("/pay/v1/transfers", json=_transfer("SARANA-PAY-IDEM"))

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["transfer"]["transfer_ref"] == second.json()["transfer"]["transfer_ref"]
    assert (await client.get("/mock/v1/state")).json()["recorded"]["transfers"] == 1


async def test_an_implausible_amount_is_refused_at_the_rail(client: AsyncClient) -> None:
    """A transfer far above any entitlement is refused rather than accepted and reversed.

    The last line before money leaves. A ten-million-rupee payment to one household is a
    data-entry error, and catching it here costs nothing.
    """
    response = await client.post(
        "/pay/v1/transfers", json=_transfer("SARANA-PAY-HUGE", amount_lkr_cents=9_000_000_00)
    )

    assert response.status_code == 422


async def test_every_payment_reference_admits_it_is_a_mock(client: AsyncClient) -> None:
    """`MOCK-` first, as in `ledger_svc.adapters.rails`.

    Not a suffix and not a field beside it: the first characters of the string anybody
    pastes into a ticket.
    """
    response = await client.post("/pay/v1/transfers", json=_transfer("SARANA-PAY-PREFIX"))

    assert response.json()["transfer"]["transfer_ref"].startswith("MOCK-")


async def test_a_malformed_nic_is_invalid_not_missing(client: AsyncClient) -> None:
    """A typo and a registry gap are different answers with different next steps."""
    response = await client.post("/hhreg/v1/verify-nic", json={"nic": "not-a-nic"})

    assert response.status_code == 200
    assert response.json()["verification"]["outcome"] == "invalid"


async def test_both_nic_formats_are_accepted(client: AsyncClient) -> None:
    """Old nine-digit cards are still valid and still held by millions of people.

    Code that only parses the twelve-digit form rejects everyone issued a card before
    2016 — disproportionately older people, who are disproportionately likely to need
    relief.
    """
    for nic in ("199012345678", "851234567V"):
        response = await client.post("/hhreg/v1/verify-nic", json={"nic": nic})
        assert response.json()["verification"]["outcome"] in {"valid", "not_found"}


async def test_a_share_of_valid_nics_are_not_on_the_register(client: AsyncClient) -> None:
    """Roughly one well-formed NIC in twelve does not resolve.

    The gap is the feature. A platform that cannot take a household through assessment and
    payment without a registry confirmation excludes the people whose paperwork is worst,
    who are reliably the people who need relief most.
    """
    import random

    rng = random.Random(20251128)  # noqa: S311 - test fixture
    outcomes = []
    for _ in range(400):
        nic = generate_nic(rng)
        response = await client.post("/hhreg/v1/verify-nic", json={"nic": nic})
        outcomes.append(response.json()["verification"]["outcome"])

    assert "invalid" not in outcomes, "generated NICs must be well-formed"
    missing = outcomes.count("not_found") / len(outcomes)
    assert abs(missing - NOT_FOUND_SHARE) < 0.05, (
        f"{missing:.1%} of valid NICs were missing; expected about {NOT_FOUND_SHARE:.0%}"
    )


async def test_verification_returns_a_division_and_never_a_name(client: AsyncClient) -> None:
    """A verified NIC resolves to a division, not to a person.

    An endpoint that hands back a name for any number presented to it is a bulk lookup
    facility with a verification label on it.
    """
    import random

    rng = random.Random(7)  # noqa: S311 - test fixture
    for _ in range(200):
        body = (await client.post("/hhreg/v1/verify-nic", json={"nic": generate_nic(rng)})).json()[
            "verification"
        ]
        assert set(body) <= {"nic", "outcome", "gn_division_code"}
        if body["outcome"] == "valid":
            assert body["gn_division_code"].startswith("LK-")
            return
    raise AssertionError("no NIC verified in 200 tries; the not-found share is wrong")
