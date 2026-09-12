"""Fan-out, and proving afterwards who was reached.

The "prove afterwards" half is what was missing during Ditwah, so it is treated here as a
deliverable rather than telemetry.

Two rules run through this module:

**Never a percentage without a denominator.** "82% delivered" is unactionable. "9,412 of
11,480 targeted handsets confirmed, 1,203 unconfirmed, 865 with no channel available" tells
an operator how many vehicles to send and where.

**Unconfirmed is not delivered.** A channel that cannot confirm reports UNKNOWN, and
UNKNOWN counts against coverage. Rounding it up to delivered would produce a map that says
a village was warned when nobody knows whether it was.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from alerting_svc.adapters.channels.base import (
    Channel,
    ChannelResult,
    DeliveryStatus,
    Message,
    Target,
    languages_for,
)

_log = structlog.get_logger(__name__)

# A division below this confirmed fraction is a gap: somewhere to send a vehicle with a
# loudhailer. Set high on purpose - the cost of over-reporting a gap is a wasted trip.
GAP_THRESHOLD: Final = 0.70

# Statuses that count as the message having reached a handset.
CONFIRMED: Final[frozenset[DeliveryStatus]] = frozenset(
    {DeliveryStatus.DELIVERED, DeliveryStatus.SENT}
)


@dataclass(frozen=True, slots=True)
class DeliverySummary:
    """The counts, always with their denominator."""

    targeted: int
    confirmed: int
    unconfirmed: int
    failed: int
    no_channel: int
    by_channel: dict[str, dict[str, int]] = field(default_factory=dict)
    by_language: dict[str, int] = field(default_factory=dict)
    channels_failed: list[str] = field(default_factory=list)

    @property
    def confirmed_fraction(self) -> float:
        """Confirmed over targeted. Zero targets is zero coverage, not complete coverage."""
        return self.confirmed / self.targeted if self.targeted else 0.0

    def as_sentence(self) -> str:
        """The phrasing the console shows. Never a bare percentage."""
        return (
            f"{self.confirmed:,} of {self.targeted:,} targeted confirmed, "
            f"{self.unconfirmed:,} unconfirmed, {self.failed:,} failed, "
            f"{self.no_channel:,} with no channel available"
        )


@dataclass(frozen=True, slots=True)
class DivisionGap:
    """A division that probably did not get the warning."""

    gn_division_code: str
    targeted: int
    confirmed: int

    @property
    def confirmed_fraction(self) -> float:
        return self.confirmed / self.targeted if self.targeted else 0.0

    def as_sentence(self) -> str:
        return (
            f"{self.gn_division_code}: {self.confirmed} of {self.targeted} confirmed "
            f"({self.confirmed_fraction:.0%})"
        )


async def fan_out(
    channels: list[Channel],
    targets: list[Target],
    body_by_language: dict[str, str],
    *,
    division_languages: dict[str, list[str]] | None = None,
) -> list[ChannelResult]:
    """Send over every channel at once.

    Concurrent by construction, and a channel that raises is recorded as having failed
    outright without touching the others. `return_exceptions=True` is doing real work
    here: without it one adapter's exception would cancel five sibling tasks mid-send, and
    an alert would go out to fewer people because an unrelated integration was broken.
    """

    async def run(channel: Channel) -> ChannelResult:
        messages = [
            Message(
                target=target,
                language=language,
                body=body_by_language.get(language, ""),
            )
            for target in targets
            for language in languages_for(
                target, channel.name, division_languages=division_languages
            )
        ]
        receipts = await channel.send(messages)
        return ChannelResult(channel=channel.name, receipts=receipts)

    outcomes = await asyncio.gather(*(run(channel) for channel in channels), return_exceptions=True)

    results: list[ChannelResult] = []
    for channel, outcome in zip(channels, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            _log.error(
                "channel_failed_outright",
                channel=channel.name,
                error=type(outcome).__name__,
                detail=str(outcome),
            )
            results.append(ChannelResult(channel=channel.name, error=str(outcome)))
        else:
            results.append(outcome)

    return results


def summarise(results: list[ChannelResult], targets: list[Target]) -> DeliverySummary:
    """Aggregate every channel's receipts into one picture.

    A target counts as confirmed if **any** channel confirmed it. Someone who got the SMS
    and not the push has been warned, and counting them once is what makes the denominator
    the number of people rather than the number of messages.
    """
    confirmed_targets: set[str] = set()
    unconfirmed_targets: set[str] = set()
    failed_targets: set[str] = set()
    no_channel_targets: set[str] = set()

    by_channel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_language: dict[str, int] = defaultdict(int)
    channels_failed: list[str] = []

    for result in results:
        if result.failed_outright:
            channels_failed.append(result.channel)
            continue
        for receipt in result.receipts:
            by_channel[result.channel][receipt.status.value] += 1
            if receipt.status in CONFIRMED:
                confirmed_targets.add(receipt.target_ref_hash)
                if receipt.language:
                    by_language[receipt.language] += 1
            elif receipt.status is DeliveryStatus.FAILED:
                failed_targets.add(receipt.target_ref_hash)
            elif receipt.status is DeliveryStatus.NO_CHANNEL:
                no_channel_targets.add(receipt.target_ref_hash)
            else:
                unconfirmed_targets.add(receipt.target_ref_hash)

    # A target confirmed anywhere is confirmed, so remove it from the weaker buckets.
    unconfirmed_targets -= confirmed_targets
    failed_targets -= confirmed_targets
    no_channel_targets -= confirmed_targets | unconfirmed_targets | failed_targets

    # Anyone no channel even attempted. Silent omission is the failure this catches.
    attempted = confirmed_targets | unconfirmed_targets | failed_targets | no_channel_targets
    untouched = {target.target_ref_hash for target in targets} - attempted
    no_channel_targets |= untouched

    return DeliverySummary(
        targeted=len(targets),
        confirmed=len(confirmed_targets),
        unconfirmed=len(unconfirmed_targets),
        failed=len(failed_targets),
        no_channel=len(no_channel_targets),
        by_channel={name: dict(counts) for name, counts in by_channel.items()},
        by_language=dict(by_language),
        channels_failed=channels_failed,
    )


def gaps(
    results: list[ChannelResult],
    targets: list[Target],
    *,
    threshold: float = GAP_THRESHOLD,
) -> list[DivisionGap]:
    """Divisions below the confirmed-delivery threshold, worst first.

    The operationally important output of this whole service: it tells a DMC operator
    which communities probably did not get the warning, while there is still time to send
    someone.
    """
    confirmed_by_target: set[str] = {
        receipt.target_ref_hash
        for result in results
        if not result.failed_outright
        for receipt in result.receipts
        if receipt.status in CONFIRMED
    }

    per_division: dict[str, list[Target]] = defaultdict(list)
    for target in targets:
        per_division[target.gn_division_code].append(target)

    found = [
        DivisionGap(
            gn_division_code=code,
            targeted=len(division_targets),
            confirmed=sum(
                1 for target in division_targets if target.target_ref_hash in confirmed_by_target
            ),
        )
        for code, division_targets in per_division.items()
    ]

    below = [gap for gap in found if gap.confirmed_fraction < threshold]
    return sorted(below, key=lambda gap: gap.confirmed_fraction)


@dataclass(frozen=True, slots=True)
class DryRun:
    """What an alert would do, computed without sending anything.

    Shown on the confirm screen every time. A misconfigured area selection that targets all
    14,022 divisions has to be caught here, before twenty million messages.
    """

    targeted: int
    by_channel: dict[str, int]
    by_language: dict[str, int]
    estimated_cost_lkr: float
    exceeds_cap: bool
    cap: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "targeted": self.targeted,
            "by_channel": self.by_channel,
            "by_language": self.by_language,
            "estimated_cost_lkr": round(self.estimated_cost_lkr, 2),
            "exceeds_cap": self.exceeds_cap,
            "cap": self.cap,
        }


# Indicative only, and per message rather than per person. SMS is the one that costs real
# money at national scale, which is why the cap exists.
COST_PER_MESSAGE_LKR: Final[dict[str, float]] = {
    "SMS": 1.75,
    "USSD": 0.90,
    "PUSH": 0.0,
    "APP": 0.0,
    "LORA": 0.0,
    "RADIO": 0.0,
    "PAPER_QR": 0.0,
}


def dry_run(
    channels: list[Channel],
    targets: list[Target],
    *,
    cap: int,
    division_languages: dict[str, list[str]] | None = None,
) -> DryRun:
    """Count what would be sent, and what it would cost. Sends nothing."""
    by_channel: dict[str, int] = {}
    by_language: dict[str, int] = defaultdict(int)
    cost = 0.0

    for channel in channels:
        count = 0
        for target in targets:
            for language in languages_for(
                target, channel.name, division_languages=division_languages
            ):
                count += 1
                by_language[language] += 1
        by_channel[channel.name] = count
        cost += count * COST_PER_MESSAGE_LKR.get(channel.name, 0.0)

    return DryRun(
        targeted=len(targets),
        by_channel=by_channel,
        by_language=dict(by_language),
        estimated_cost_lkr=cost,
        exceeds_cap=len(targets) > cap,
        cap=cap,
    )
