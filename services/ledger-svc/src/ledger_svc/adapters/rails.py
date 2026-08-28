"""Mock payment rails.

Every rail in Phase 1 is a mock, and every reference it returns says so. The interface is
real because the gate above it has to be exercised properly; the transport is not, and a
demo that produced references indistinguishable from a bank's would be one screenshot away
from being mistaken for a live disbursement.

`MOCK-` is the prefix on every reference. Not a configuration flag, not a suffix, not a
field beside it - the first six characters of the string anybody pastes into a ticket.
"""

from __future__ import annotations

import asyncio
from typing import Final

import structlog

from sarana_shared.domain.ids import uuid7

_log = structlog.get_logger(__name__)

MOCK_PREFIX: Final = "MOCK-"

# The rails `aid.disbursement.payment_rail` accepts, and what each one is standing in for.
RAIL_DESCRIPTIONS: Final[dict[str, str]] = {
    "BANK_TRANSFER": "a batch file to a commercial bank",
    "MOBILE_MONEY": "an operator wallet credit",
    "POST_OFFICE": "a payment order collected at a post office counter",
    "CASH": "cash handed over by a DS officer against a signature",
}


class RailUnavailable(RuntimeError):
    """The rail refused or could not be reached. Nothing was moved."""


class MockRail:
    """A rail that succeeds and says it is a mock.

    Deliberately has no failure injection knob. A rail that sometimes fails on a demo is a
    rail whose failures get explained away as the demo; `FailingRail` exists for the tests
    that need a refusal, and it is chosen explicitly.
    """

    def __init__(self, name: str = "BANK_TRANSFER", *, latency_seconds: float = 0.0) -> None:
        if name not in RAIL_DESCRIPTIONS:
            raise ValueError(
                f"{name!r} is not a payment rail the ledger recognises; expected one of "
                f"{', '.join(sorted(RAIL_DESCRIPTIONS))}"
            )
        self.name = name
        self._latency = latency_seconds

    async def send(self, *, amount_lkr_cents: int, reference: str) -> str:
        """Pretend to move the money. Returns a reference that admits it."""
        if self._latency:
            await asyncio.sleep(self._latency)

        payment_ref = f"{MOCK_PREFIX}{self.name}-{uuid7().hex[:12].upper()}"
        _log.info(
            "mock_payment_sent",
            rail=self.name,
            amount_lkr_cents=amount_lkr_cents,
            reference=reference,
            payment_ref=payment_ref,
            simulated=True,
        )
        return payment_ref


class FailingRail:
    """A rail that always refuses. For the test that a failed rail records nothing."""

    def __init__(self, name: str = "BANK_TRANSFER") -> None:
        self.name = name

    async def send(self, *, amount_lkr_cents: int, reference: str) -> str:
        raise RailUnavailable(
            f"the {self.name} rail refused this transfer. Nothing has been recorded."
        )


def build_rail(name: str) -> MockRail:
    """The rail for one release. Phase 1 has exactly one implementation."""
    return MockRail(name)
