"""Everything the mocks remember, in one place.

Two kinds of data live in this service and they are kept strictly apart:

  **Generated** — rainfall, shelters, households, officers, coverage. Pure functions of
  `(seed, entity, simulated hour)`, computed on read, never stored. Restarting the
  container changes nothing about them.

  **Recorded** — claims pushed into the CMS, transfers submitted to the rail, messages
  handed to the gateway, occupancy somebody counted by hand. These are things that
  happened, so they are held here and lost on restart.

Held in memory rather than in Postgres on purpose. gov-mock owns no schema and stands in
for systems outside SARANA entirely; giving it tables in the platform's own database would
put an external system's records inside the boundary the platform is audited on. Restarting
the mock is meant to be the way you reset it.

**This means one replica.** Two replicas would disagree about a claim's status, and a
poller would see it flip. Fine for a mock; stated here so nobody scales it and spends an
afternoon on the consequences.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from gov_mock.chaos import ChaosController
from gov_mock.clock import SimulatedClock
from gov_mock.data.dmc import SafetyLocation, build_locations

# The only scenario shipped with file 11. File 28 adds the rest; this one exists so the
# control plane has something real to load and so the demo has a story.
DEFAULT_SCENARIO: Final = "ditwah_kandy"

KNOWN_SCENARIOS: Final[frozenset[str]] = frozenset({DEFAULT_SCENARIO, "quiet"})


@dataclass(slots=True)
class OccupancyCount:
    """A headcount somebody actually took, overriding the modelled curve."""

    location_id: str
    occupancy: int
    counted_at: datetime


@dataclass(slots=True)
class Claim:
    """A claim pushed into the CMS."""

    claim_reference: str
    client_reference: str
    household_reference: str
    amount_lkr_cents: int
    received_at: datetime
    updated_at: datetime
    payload: dict[str, Any]


@dataclass(slots=True)
class Transfer:
    """A transfer instructed on the payment rail."""

    transfer_ref: str
    client_reference: str
    amount_lkr_cents: int
    rail: str
    beneficiary_ref_hash: str
    accepted_at: datetime


@dataclass(slots=True)
class Message:
    """One message handed to the telco gateway."""

    message_id: str
    recipient_ref_hash: str
    body: str
    language: str
    accepted_at: datetime
    # True once a delivery receipt has been posted back to alerting-svc, so the DLR
    # dispatcher does not send the same receipt twice.
    receipt_sent: bool = False


@dataclass(slots=True)
class InboundMessage:
    """An SMS or USSD session a demoer sent *into* the platform from the simulator page.

    Kept so the simulator can show what it sent and what came back. This is the only
    inbound direction in the whole service, and it exists because a demo where nobody can
    play the part of a citizen with a feature phone is a demo about dashboards.
    """

    received_at: datetime
    msisdn: str
    language: str
    channel: str
    body: str
    forwarded_to: str
    status_code: int | None
    response_excerpt: str


@dataclass(slots=True)
class Webhook:
    """A settlement callback the payment rail was asked to make."""

    webhook_id: str
    url: str
    events: tuple[str, ...]
    registered_at: datetime


class MockState:
    """The service's whole memory. One instance, held on `app.state`."""

    def __init__(self, *, seed: int, clock: SimulatedClock, chaos: ChaosController) -> None:
        self.seed = seed
        self.clock = clock
        self.chaos = chaos
        self.scenario_id: str | None = None

        self._lock = threading.Lock()
        self.locations: list[SafetyLocation] = build_locations(seed=seed)
        self.locations_by_id: dict[str, SafetyLocation] = {
            location.location_id: location for location in self.locations
        }

        self.occupancy_counts: dict[str, OccupancyCount] = {}
        self.claims: dict[str, Claim] = {}
        self.claims_by_client_ref: dict[str, str] = {}
        self.transfers: dict[str, Transfer] = {}
        self.transfers_by_client_ref: dict[str, str] = {}
        self.messages: dict[str, Message] = {}
        self.webhooks: dict[str, Webhook] = {}
        self.inbound: list[InboundMessage] = []

        self._sequence = 0

    def next_sequence(self) -> int:
        """A monotonic counter for generated references.

        Locked because uvicorn will happily run two requests concurrently, and two claims
        sharing a reference is the one bug a claims mock must not have.
        """
        with self._lock:
            self._sequence += 1
            return self._sequence

    def load_scenario(self, scenario_id: str) -> None:
        """Reset to the start of a scenario.

        Everything recorded is discarded. A scenario that kept the previous run's claims
        would replay differently the second time, which defeats the point of loading one.
        """
        self.scenario_id = scenario_id
        self.occupancy_counts.clear()
        self.claims.clear()
        self.claims_by_client_ref.clear()
        self.transfers.clear()
        self.transfers_by_client_ref.clear()
        self.messages.clear()
        self.inbound.clear()
        # Webhooks deliberately survive: a registered callback URL is a fact about how the
        # platform is wired, not part of the story being told.
        self.chaos.reset()
        self.clock.reset(offset=_scenario_start(scenario_id))

    def recorded_counts(self) -> dict[str, int]:
        """What the service is holding, for `GET /mock/v1/state`."""
        return {
            "safety_locations": len(self.locations),
            "occupancy_counts": len(self.occupancy_counts),
            "claims": len(self.claims),
            "transfers": len(self.transfers),
            "messages": len(self.messages),
            "webhooks": len(self.webhooks),
            "inbound_messages": len(self.inbound),
        }


def _scenario_start(scenario_id: str) -> timedelta:
    """Where on the timeline a scenario begins.

    `ditwah_kandy` starts three days before landfall, because the anticipatory action the
    platform exists to enable happens in those three days. Starting at landfall would skip
    the only part of the story where a forecast can still change an outcome.
    """
    if scenario_id == "quiet":
        # Far enough past the event that every curve has decayed to background. The
        # scenario for testing that nothing fires when nothing is happening.
        return timedelta(days=14)
    return timedelta(hours=-72)
