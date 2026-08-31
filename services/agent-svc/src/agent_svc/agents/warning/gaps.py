"""Who was probably not reached, per division, while there is still time to go and tell them.

During Ditwah the gap between "warning issued" and "warning received" is exactly where
people died. Making that gap visible is not telemetry for an after-action report; it is the
output an officer acts on during the event, and it is the reason this module exists as a
deliverable rather than as a logging concern.

Two rules run through every number here, and both are load-bearing.

**Never a percentage without its denominator.** "82% delivered" is unactionable. "9,412 of
11,480 confirmed, 1,203 unconfirmed, 865 with no channel available" tells an officer how
many vehicles to send and where. Every type below carries the denominator with the figure
so the two cannot be separated by a caller in a hurry.

**Unconfirmed is not delivered.** A channel that cannot confirm reports UNKNOWN, and
UNKNOWN counts against coverage. Rounding it up would produce a map that says a village was
warned when nobody knows whether it was, and the officer reading that map does not send the
vehicle.

## reachability_confidence, and what it is confidence *about*

It is not "how likely is it that these people got the message". It is **how much of this
division's picture we actually know** - the share of targeted households whose outcome is a
definite one, in either direction. A division where every receipt came back UNKNOWN scores
low even if the truth is that everybody got it, because the honest statement is that we
cannot tell.

Separating the two is what stops the number from flattering itself. A confident 40%
confirmed is a division to send a vehicle to. An unconfident 90% confirmed is a division to
send a vehicle to *and* fix the receipts on.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from agent_svc.agents.warning.ports import ChannelOutcome, WarningTarget

_log = structlog.get_logger(__name__)

# A division below this confirmed fraction is a gap. The same figure as
# `alerting_svc.domain.delivery.GAP_THRESHOLD`, and set high on purpose: the cost of
# over-reporting a gap is a wasted trip, and the cost of under-reporting one is a village
# nobody visits.
GAP_THRESHOLD: Final = 0.70

# What an outright channel failure costs the confidence in every division it touched. A
# channel that never ran might have reached anyone; we do not know who, so we say we do not
# know. Applied once per failed channel rather than per message.
CHANNEL_FAILURE_PENALTY: Final = 0.25

# The floor. Never zero while any target has a definite outcome, because a division we know
# something about is not a division we know nothing about.
MIN_CONFIDENCE: Final = 0.05


@dataclass(frozen=True, slots=True)
class DivisionGap:
    """One division's delivery picture, with its denominator attached.

    The five counts partition the targets exactly once each. A target confirmed on any
    channel is confirmed - somebody who got the SMS and not the push has been warned, and
    counting them once is what makes the denominator the number of households rather than
    the number of messages.
    """

    gn_division_code: str
    targeted: int
    confirmed: int
    failed: int
    unconfirmed: int
    no_channel_available: int
    reachability_confidence: float
    channels_failed: tuple[str, ...] = ()

    @property
    def confirmed_fraction(self) -> float:
        """Confirmed over targeted. Zero targets is zero coverage, not complete coverage."""
        return self.confirmed / self.targeted if self.targeted else 0.0

    @property
    def is_gap(self) -> bool:
        return self.confirmed_fraction < GAP_THRESHOLD

    def as_sentence(self) -> str:
        """What the console shows. Never a bare percentage."""
        line = (
            f"{self.gn_division_code}: {self.confirmed:,} of {self.targeted:,} confirmed, "
            f"{self.unconfirmed:,} unconfirmed, {self.failed:,} failed, "
            f"{self.no_channel_available:,} with no channel available"
        )
        if self.reachability_confidence < GAP_THRESHOLD:
            line += f" (this picture is {self.reachability_confidence:.0%} complete)"
        return line

    def as_dict(self) -> dict[str, Any]:
        """The shape `/api/v1/alerts/{id}/delivery/gaps` and the console read."""
        return {
            "gn_division_code": self.gn_division_code,
            "targeted": self.targeted,
            "confirmed": self.confirmed,
            "failed": self.failed,
            "unconfirmed": self.unconfirmed,
            "no_channel_available": self.no_channel_available,
            "confirmed_fraction": round(self.confirmed_fraction, 4),
            "reachability_confidence": round(self.reachability_confidence, 4),
            "channels_failed": list(self.channels_failed),
            "summary": self.as_sentence(),
        }


@dataclass(frozen=True, slots=True)
class GapReport:
    """Every division's picture, and the national totals under the same rules."""

    divisions: list[DivisionGap] = field(default_factory=list)
    channels_failed: tuple[str, ...] = ()

    @property
    def gaps(self) -> list[DivisionGap]:
        """Divisions below the threshold, worst first.

        The operationally important output of the whole agent: it names where to send a
        vehicle with a loudhailer, in time for that to matter.
        """
        return sorted(
            (division for division in self.divisions if division.is_gap),
            key=lambda division: division.confirmed_fraction,
        )

    @property
    def targeted(self) -> int:
        return sum(division.targeted for division in self.divisions)

    @property
    def confirmed(self) -> int:
        return sum(division.confirmed for division in self.divisions)

    @property
    def unconfirmed(self) -> int:
        return sum(division.unconfirmed for division in self.divisions)

    @property
    def failed(self) -> int:
        return sum(division.failed for division in self.divisions)

    @property
    def no_channel_available(self) -> int:
        return sum(division.no_channel_available for division in self.divisions)

    def as_sentence(self) -> str:
        """The national figure, in the phrasing the console shows."""
        return (
            f"{self.confirmed:,} of {self.targeted:,} targeted confirmed, "
            f"{self.unconfirmed:,} unconfirmed, {self.failed:,} failed, "
            f"{self.no_channel_available:,} with no channel available"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "targeted": self.targeted,
            "confirmed": self.confirmed,
            "unconfirmed": self.unconfirmed,
            "failed": self.failed,
            "no_channel_available": self.no_channel_available,
            "channels_failed": list(self.channels_failed),
            "divisions_below_threshold": len(self.gaps),
            "summary": self.as_sentence(),
        }


def assess(outcomes: list[ChannelOutcome], targets: list[WarningTarget]) -> GapReport:
    """Turn every channel's receipts into one picture per division.

    A target lands in exactly one bucket, resolved in order of how much it tells us:
    confirmed anywhere beats failed anywhere beats unconfirmed beats no channel. Anyone no
    channel even attempted is `no_channel_available` - silent omission is the failure this
    catches, and it is silent precisely because nothing produced a record to notice.
    """
    failed_channels = tuple(
        sorted(outcome.channel for outcome in outcomes if outcome.failed_outright)
    )

    confirmed: set[str] = set()
    failed: set[str] = set()
    unconfirmed: set[str] = set()
    no_channel: set[str] = set()

    for outcome in outcomes:
        if outcome.failed_outright:
            continue
        for receipt in outcome.receipts:
            if receipt.confirmed:
                confirmed.add(receipt.target_key)
            elif receipt.status == "NO_CHANNEL":
                no_channel.add(receipt.target_key)
            elif receipt.status in {"FAILED", "EXPIRED"}:
                failed.add(receipt.target_key)
            else:
                unconfirmed.add(receipt.target_key)

    # Resolved in order. A household confirmed on the app and failed on SMS was warned.
    failed -= confirmed
    unconfirmed -= confirmed | failed
    no_channel -= confirmed | failed | unconfirmed

    attempted = confirmed | failed | unconfirmed | no_channel
    untouched = {target.key for target in targets} - attempted
    no_channel |= untouched

    by_division: dict[str, list[WarningTarget]] = defaultdict(list)
    for target in targets:
        by_division[target.gn_division_code].append(target)

    divisions = [
        _division_gap(code, members, confirmed, failed, unconfirmed, no_channel, failed_channels)
        for code, members in sorted(by_division.items())
    ]

    report = GapReport(divisions=divisions, channels_failed=failed_channels)
    _log.info(
        "warning_gaps_assessed",
        targeted=report.targeted,
        confirmed=report.confirmed,
        unconfirmed=report.unconfirmed,
        no_channel_available=report.no_channel_available,
        divisions_below_threshold=len(report.gaps),
        channels_failed=list(failed_channels),
    )
    return report


def _division_gap(
    code: str,
    members: list[WarningTarget],
    confirmed: set[str],
    failed: set[str],
    unconfirmed: set[str],
    no_channel: set[str],
    channels_failed: tuple[str, ...],
) -> DivisionGap:
    keys = [target.key for target in members]
    counts = {
        "confirmed": sum(1 for key in keys if key in confirmed),
        "failed": sum(1 for key in keys if key in failed),
        "unconfirmed": sum(1 for key in keys if key in unconfirmed),
        "no_channel_available": sum(1 for key in keys if key in no_channel),
    }
    return DivisionGap(
        gn_division_code=code,
        targeted=len(keys),
        reachability_confidence=reachability_confidence(
            targeted=len(keys),
            definite=counts["confirmed"] + counts["failed"] + counts["no_channel_available"],
            channels_failed=len(channels_failed),
        ),
        channels_failed=channels_failed,
        **counts,
    )


def reachability_confidence(*, targeted: int, definite: int, channels_failed: int) -> float:
    """How complete this division's delivery picture is, between 0 and 1.

    Not how likely the message arrived. The share of households whose outcome is known one
    way or the other, reduced for every channel that never ran - because a channel that
    failed outright might have reached anybody, and not knowing who is exactly the thing
    this number reports.

    Zero targets scores zero. A division with nobody in it is not a division we have
    complete information about; it is one the targeting produced nothing for, and that is
    worth looking at rather than reporting as certainty.
    """
    if targeted <= 0:
        return 0.0

    known = definite / targeted
    penalised = known * (1.0 - CHANNEL_FAILURE_PENALTY) ** max(0, channels_failed)
    return round(max(MIN_CONFIDENCE, min(1.0, penalised)), 4)
