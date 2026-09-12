"""Synthetic telco data: three operators that behave differently, and coverage that fails.

The three operators are not colour. Each one exists to force a behaviour the platform must
have:

  **DIALOG** — fast receipts, low failure. The easy case, and the one that makes everything
  look fine if it is the only one tested against.
  **MOBITEL** — slow receipts and a lower throughput cap. Forces the caller to cope with a
  fan-out that is still draining minutes later.
  **HUTCH** — sends no delivery receipt for about 2% of messages, ever. Not late: never.
  This is why `UNKNOWN` is a distinct delivery state from `FAILED` in `alerting_svc`, and
  why it counts against coverage. A message that may or may not have arrived is not a
  message that arrived.

**Coverage degrades during the event, and it is the same baseline SARANA holds.**
`baseline_coverage_pct` mirrors `tools/seed/generate.py`'s `cell_coverage_pct` exactly, so
the mock and `admin.gn_division` agree about a division on a normal day; a test asserts it.
What the mock adds is the part the seed cannot have: cell sites lose mains power as the
storm passes, run their batteries down over the following hours, and coverage falls. The
warning stops arriving exactly when it matters most, which is the single most important
thing this mock has to be able to demonstrate.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from gov_mock.data.derive import seed_for
from gov_mock.data.districts import GN_PER_DS, district_for
from gov_mock.data.dmc import AFFECTED_DISTRICTS


class Operator(StrEnum):
    """The three modelled operators."""

    DIALOG = "DIALOG"
    MOBITEL = "MOBITEL"
    HUTCH = "HUTCH"


@dataclass(frozen=True, slots=True)
class OperatorProfile:
    """How one operator behaves."""

    operator: Operator
    # Share of national subscribers. Drives which operator a recipient is drawn onto.
    market_share: float
    # Messages the gateway will accept per second. A national fan-out is limited by this,
    # not by how fast the platform can generate messages.
    throughput_per_second: int
    # Seconds before a delivery receipt is posted back.
    dlr_latency_seconds: float
    # Share of messages that fail outright, with a receipt saying so.
    failure_rate: float
    # Share of messages that get no receipt at all, ever. `UNKNOWN`, not `FAILED`.
    silent_drop_rate: float


PROFILES: Final[dict[Operator, OperatorProfile]] = {
    Operator.DIALOG: OperatorProfile(
        operator=Operator.DIALOG,
        market_share=0.45,
        throughput_per_second=200,
        dlr_latency_seconds=4.0,
        failure_rate=0.012,
        silent_drop_rate=0.0,
    ),
    Operator.MOBITEL: OperatorProfile(
        operator=Operator.MOBITEL,
        market_share=0.35,
        throughput_per_second=80,
        dlr_latency_seconds=25.0,
        failure_rate=0.020,
        silent_drop_rate=0.0,
    ),
    Operator.HUTCH: OperatorProfile(
        operator=Operator.HUTCH,
        market_share=0.20,
        throughput_per_second=60,
        dlr_latency_seconds=12.0,
        failure_rate=0.025,
        # The 2% that never produces a receipt. Build file 09's `UNKNOWN` state exists
        # for these, and folding them into DELIVERED would produce a map claiming a
        # village was warned when nobody knows.
        silent_drop_rate=0.020,
    ),
}

FAILURE_REASONS: Final[tuple[str, ...]] = (
    "handset unreachable",
    "number not in service",
    "message expired in queue",
    "SIM not provisioned for this service",
)

# Cell sites per GN division. Small, because a GN division is small: one or two masts, and
# losing one is losing half the division's coverage.
SITES_MIN: Final = 1
SITES_MAX: Final = 4

# When mains power fails and how long batteries last. Sri Lankan cell sites carry a few
# hours of battery; beyond that a site is down until a generator reaches it, which during a
# cyclone means days.
POWER_LOSS_HOUR: Final = -2.0
BATTERY_HOURS: Final = 6.0
RECOVERY_HOUR: Final = 60.0

# Coverage a division retains with every site down. Not zero: a mast in the neighbouring
# division still reaches part of the population, and claiming total blackout would
# overstate the gap as badly as claiming none.
RESIDUAL_COVERAGE_PCT: Final = 12.0


def baseline_coverage_pct(gn_division_code: str) -> float:
    """Normal-day coverage for a division.

    Mirrors `tools/seed/generate.py`: `round(70.0 + (gn_index * 5.1) % 30, 2)`. Reproduced
    rather than imported, for the same reason the landslide zonation is — this service
    stands in for an operator's own network inventory and must not depend on SARANA's seed
    tooling. A test asserts the two agree.
    """
    parts = gn_division_code.split("-")
    if len(parts) != 4 or not parts[3].isdigit():
        raise ValueError(f"not a GN division code: {gn_division_code!r}")
    gn_index = int(parts[3])
    if not 1 <= gn_index <= GN_PER_DS:
        raise ValueError(f"GN division code out of range: {gn_division_code!r}")
    return round(70.0 + (gn_index * 5.1) % 30, 2)


def _sites(gn_division_code: str, *, seed: int) -> int:
    rng = random.Random(seed_for(seed, "sites", gn_division_code))  # noqa: S311 - synthetic
    return rng.randrange(SITES_MIN, SITES_MAX + 1)


@dataclass(frozen=True, slots=True)
class CoverageState:
    """Coverage for one division at the current simulated hour."""

    gn_division_code: str
    percent: float
    operators: tuple[Operator, ...]
    sites_on_battery: int
    sites_down: int


def coverage_for(gn_division_code: str, *, hours_since_landfall: float, seed: int) -> CoverageState:
    """Modelled coverage now, after power loss and battery exhaustion.

    Unaffected districts keep their baseline. In the affected ones, sites drop to battery
    around landfall and start going dark once the batteries run out, recovering slowly as
    generators arrive.
    """
    baseline = baseline_coverage_pct(gn_division_code)
    total_sites = _sites(gn_division_code, seed=seed)
    district = district_for(gn_division_code)
    operators = _operators_for(gn_division_code, seed=seed)

    if district is None or district.code not in AFFECTED_DISTRICTS:
        return CoverageState(
            gn_division_code=gn_division_code,
            percent=baseline,
            operators=operators,
            sites_on_battery=0,
            sites_down=0,
        )

    rng = random.Random(seed_for(seed, "power", gn_division_code))  # noqa: S311 - synthetic
    # Sites do not all fail together. Each carries its own offset, so a division degrades
    # in steps rather than falling off a cliff — which is what an operator watching a
    # coverage map actually sees.
    offsets = [rng.uniform(-4.0, 8.0) for _ in range(total_sites)]

    on_battery = 0
    down = 0
    for offset in offsets:
        lost_power_at = POWER_LOSS_HOUR + offset
        dead_at = lost_power_at + BATTERY_HOURS
        recovered_at = RECOVERY_HOUR + offset

        if hours_since_landfall < lost_power_at or hours_since_landfall >= recovered_at:
            continue
        if hours_since_landfall < dead_at:
            on_battery += 1
        else:
            down += 1

    # A site on battery still carries traffic; only a dead one removes coverage.
    working = total_sites - down
    if total_sites == 0 or working <= 0:
        percent = RESIDUAL_COVERAGE_PCT
    else:
        share = working / total_sites
        percent = RESIDUAL_COVERAGE_PCT + (baseline - RESIDUAL_COVERAGE_PCT) * share

    return CoverageState(
        gn_division_code=gn_division_code,
        percent=round(max(0.0, min(100.0, percent)), 2),
        operators=operators,
        sites_on_battery=on_battery,
        sites_down=down,
    )


def _operators_for(gn_division_code: str, *, seed: int) -> tuple[Operator, ...]:
    """Which operators serve a division. Rural divisions are not served by all three."""
    rng = random.Random(seed_for(seed, "ops", gn_division_code))  # noqa: S311 - synthetic
    if rng.random() < 0.65:
        return (Operator.DIALOG, Operator.MOBITEL, Operator.HUTCH)
    if rng.random() < 0.6:
        return (Operator.DIALOG, Operator.MOBITEL)
    return (Operator.DIALOG,)


def operator_for(recipient_ref_hash: str, *, seed: int) -> Operator:
    """Which operator a recipient is on.

    Derived from the recipient's hash, so the same person is always on the same network.
    Drawing it per message would make a delivery gap look random instead of showing that
    one operator's subscribers are the ones being missed.
    """
    rng = random.Random(seed_for(seed, "op", recipient_ref_hash))  # noqa: S311 - synthetic
    draw = rng.random()
    cumulative = 0.0
    for profile in PROFILES.values():
        cumulative += profile.market_share
        if draw < cumulative:
            return profile.operator
    return Operator.HUTCH


@dataclass(frozen=True, slots=True)
class Outcome:
    """What happens to one message, decided at submission and never revisited."""

    operator: Operator
    delivered: bool
    silent: bool
    failure_reason: str | None

    @property
    def state(self) -> str:
        """The message state a caller will eventually see."""
        if self.silent:
            return "UNKNOWN"
        return "DELIVERED" if self.delivered else "FAILED"


def outcome_for(message_id: str, recipient_ref_hash: str, *, seed: int) -> Outcome:
    """Decide a message's fate.

    Decided once from the message id, so polling the same message twice gives the same
    answer. A mock that re-rolled on each poll would have messages recovering from FAILED,
    which no gateway does and no caller should be written to expect.
    """
    operator = operator_for(recipient_ref_hash, seed=seed)
    profile = PROFILES[operator]
    rng = random.Random(seed_for(seed, "msg", message_id))  # noqa: S311 - synthetic

    draw = rng.random()
    if draw < profile.silent_drop_rate:
        return Outcome(operator=operator, delivered=False, silent=True, failure_reason=None)
    if draw < profile.silent_drop_rate + profile.failure_rate:
        return Outcome(
            operator=operator,
            delivered=False,
            silent=False,
            failure_reason=rng.choice(FAILURE_REASONS),
        )
    return Outcome(operator=operator, delivered=True, silent=False, failure_reason=None)


def accepted_count(profile: OperatorProfile, requested: int, *, window_seconds: float = 1.0) -> int:
    """How many of a batch this operator will take right now.

    A gateway at its cap takes what it can and refuses the rest. Partial acceptance is
    normal and is not an error; the refused part has to be resent, and a caller that
    treats a partial acceptance as a failure will resend the whole batch and double
    everybody's messages.
    """
    return min(requested, math.floor(profile.throughput_per_second * window_seconds))
