"""Which channels carry this warning, and which of them wait until morning.

The model proposes and a deterministic validator has the final say. Everything below runs
whether or not a model was involved, so the channel mix during a provider outage is the
same mix, and the only thing that changes is whether anything was proposed on top of it.

## The rules, and what each one costs when it is wrong

**`impact_class >= 3` uses every available channel, no exceptions.** At major impact the
cost of a redundant SMS is a rupee and a half. The cost of a missing one is somebody who
did not leave.

**`impact_class == 2` uses the app and SMS.** Enough to reach the people who are watching
for it, without spending the country's attention on a watch-level message.

**Thin cell coverage weights up the tiers that do not need a cell network.** A division at
30% coverage is one where SMS is a partial answer by construction, and the mesh, the radio
and a printed sheet a GN officer carries door to door are the difference between a partial
answer and a gap.

**Between 22:00 and 05:00 Colombo, only `impact_class >= 3` sends SMS.** Below that it
queues to 06:00. Waking a district at 2 a.m. for a watch-level alert costs credibility that
is needed later in the same event - and during a multi-day cyclone it is needed roughly
every twelve hours. The bypass at class 3 is the whole point of the rule: the exception is
what makes the restriction safe to apply.

**A hard cap on total targets, overridable only with a reason.** A misconfigured area
selection that names half the country has to be stopped before twenty million messages,
and the reason is what makes the override a decision somebody made rather than a button
somebody clicked.

## What the model may and may not do

It may **add** an available channel the matrix did not select. It may not remove one the
matrix requires, and it may not add a channel this deployment does not have. Both of those
are enforced on its output, not asked for in its prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

import structlog

from agent_svc.agents.warning.ports import ModelCall
from sarana_shared.domain.time import COLOMBO, ensure_utc

_log = structlog.get_logger(__name__)

# Every channel the platform has. Mirrors `alerting.dispatch.channel`; a test asserts the
# two agree, because a channel this agent selects and the column rejects fails at the
# INSERT, after the warning has already gone out.
ALL_CHANNELS: Final[tuple[str, ...]] = (
    "SMS",
    "USSD",
    "PUSH",
    "APP",
    "LORA",
    "RADIO",
    "PAPER_QR",
)

# At or above this class, everything available fires.
ALL_CHANNELS_FROM: Final = 3

# The mix at moderate impact.
MODERATE_CHANNELS: Final[tuple[str, ...]] = ("APP", "PUSH", "SMS")

# Below this class the agent sends nothing at all. Class 1 is rain approaching a division's
# own threshold; a public alert there is the alert people learn to ignore before the one
# that mattered arrives.
ALERT_FROM: Final = 2

# Cell coverage at or below which the non-cellular tiers are weighted up.
LOW_COVERAGE_PCT: Final = 60.0

# The tiers that do not need a working cell network.
OFFLINE_TIERS: Final[tuple[str, ...]] = ("LORA", "RADIO", "PAPER_QR")

# Quiet hours, in Colombo local time. Inclusive of the start hour, exclusive of the end.
QUIET_START_HOUR: Final = 22
QUIET_END_HOUR: Final = 5
# When a deferred SMS is released. An hour after quiet hours end rather than on the minute,
# so a queue released at 05:00 does not arrive while people are still asleep.
QUIET_RELEASE_HOUR: Final = 6

# Channels that go quiet at night. Only the ones that make a handset make a noise: the app
# is a notification somebody sees when they wake, the mesh and the radio are not addressed
# to an individual, and a printed sheet is delivered by daylight anyway.
QUIET_HOURS_CHANNELS: Final[frozenset[str]] = frozenset({"SMS", "USSD", "PUSH"})

# The same figure as alerting-svc's `SARANA_ALERTING_TARGET_CAP` default. Duplicated
# because the agent has to refuse *before* it calls dispatch - discovering the cap from a
# 409 would mean the whole targeting run happened for nothing - and a test asserts the two
# are the same number.
DEFAULT_TARGET_CAP: Final = 250_000


@dataclass(frozen=True, slots=True)
class ChannelPlan:
    """What goes out now, what waits, and why each of them.

    `reasons` is keyed by channel and is read by the ops console. A channel plan nobody
    can explain is one nobody can override with any confidence, and the person overriding
    it at 2 a.m. is the one who most needs to know why it was made.
    """

    channels: tuple[str, ...]
    deferred: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)
    method: str = "DETERMINISTIC"
    release_at: datetime | None = None
    exceeds_cap: bool = False
    cap: int = DEFAULT_TARGET_CAP
    targeted: int = 0

    @property
    def sends_anything(self) -> bool:
        return bool(self.channels)

    def as_sentence(self) -> str:
        now = ", ".join(self.channels) or "nothing"
        if not self.deferred:
            return f"{now} now"
        when = self.release_at.isoformat(timespec="minutes") if self.release_at else "06:00"
        return f"{now} now; {', '.join(self.deferred)} queued to {when}"


def in_quiet_hours(moment: datetime) -> bool:
    """Whether it is between 22:00 and 05:00 in Colombo.

    Colombo local rather than UTC, because the rule is about when somebody is asleep and
    Sri Lanka is UTC+5:30 - applying it in UTC would silence the wrong five and a half
    hours, which during an overnight landfall is exactly the wrong five and a half.
    """
    hour = ensure_utc(moment).astimezone(COLOMBO).hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def next_release(moment: datetime) -> datetime:
    """When a message deferred at `moment` goes out.

    06:00 Colombo, today if it is still to come and tomorrow if it is not. A message
    deferred at 23:00 is released seven hours later; one deferred at 02:00 is released four
    hours later on the same calendar day.
    """
    local = ensure_utc(moment).astimezone(COLOMBO)
    release = local.replace(hour=QUIET_RELEASE_HOUR, minute=0, second=0, microsecond=0)
    if release <= local:
        release += timedelta(days=1)
    return release.astimezone(ensure_utc(moment).tzinfo)


def plan(
    *,
    impact_class: int,
    now: datetime,
    available: tuple[str, ...] = ALL_CHANNELS,
    cell_coverage_pct: float | None = None,
    targeted: int = 0,
    cap: int = DEFAULT_TARGET_CAP,
    override_cap: bool = False,
    proposed: tuple[str, ...] | None = None,
) -> ChannelPlan:
    """The channel mix, with the model's proposal folded in if there is one.

    Deterministic end to end. `proposed` is whatever a model suggested; it can only widen
    the selection, and only to channels this deployment actually has.
    """
    if impact_class < ALERT_FROM:
        return ChannelPlan(
            channels=(),
            reasons={"_": f"impact class {impact_class} is below the alerting threshold"},
            targeted=targeted,
            cap=cap,
        )

    reasons: dict[str, str] = {}
    selected: set[str] = set()

    if impact_class >= ALL_CHANNELS_FROM:
        selected = set(available)
        for channel in selected:
            reasons[channel] = (
                f"impact class {impact_class}: every available channel, no exceptions"
            )
    else:
        for channel in MODERATE_CHANNELS:
            if channel in available:
                selected.add(channel)
                reasons[channel] = "moderate impact: app and SMS"

    if cell_coverage_pct is not None and cell_coverage_pct <= LOW_COVERAGE_PCT:
        for channel in OFFLINE_TIERS:
            if channel in available and channel not in selected:
                selected.add(channel)
                reasons[channel] = (
                    f"cell coverage is {cell_coverage_pct:.0f}%: the tiers that do not need "
                    "a cell network are weighted up"
                )

    method = "DETERMINISTIC"
    if proposed:
        added = {channel for channel in proposed if channel in available} - selected
        ignored = {channel for channel in proposed if channel not in available}
        if ignored:
            # Not an error worth stopping for, but worth being loud about: a model naming a
            # transport this deployment does not have is a model working from a catalogue
            # somebody changed.
            _log.warning(
                "warning_channel_proposal_ignored",
                channels=sorted(ignored),
                reason="not available in this deployment",
            )
        for channel in added:
            reasons[channel] = "proposed by the model and available"
        if added:
            method = "LLM_WIDENED"
        selected |= added

    deferred: set[str] = set()
    release_at: datetime | None = None
    if impact_class < ALL_CHANNELS_FROM and in_quiet_hours(now):
        deferred = selected & QUIET_HOURS_CHANNELS
        selected -= deferred
        if deferred:
            release_at = next_release(now)
            for channel in deferred:
                reasons[channel] = (
                    "quiet hours: a watch-level alert does not wake a district at night; "
                    f"queued to {release_at.astimezone(COLOMBO).strftime('%H:%M')} Colombo"
                )

    exceeds = targeted > cap and not override_cap
    if exceeds:
        _log.error(
            "warning_target_cap_exceeded",
            targeted=targeted,
            cap=cap,
            impact="this alert was not dispatched; confirm the area selection and "
            "override with a written reason",
        )

    return ChannelPlan(
        channels=tuple(sorted(selected)),
        deferred=tuple(sorted(deferred)),
        reasons=reasons,
        method=method,
        release_at=release_at,
        exceeds_cap=exceeds,
        cap=cap,
        targeted=targeted,
    )


async def propose(
    *,
    impact_class: int,
    available: tuple[str, ...],
    cell_coverage_pct: float | None,
    call: ModelCall | None,
) -> tuple[str, ...]:
    """Ask the model which channels it would add. Never which it would remove.

    Returns an empty tuple for every failure - no model, an unreachable provider, an
    unparseable answer. A warning does not wait on a model provider to decide how to leave
    the building, and `plan()` above produces a complete, working mix with nothing here.
    """
    if call is None:
        return ()

    prompt = (
        "You are advising on which channels should carry a Sri Lankan disaster warning.\n"
        "Answer with a comma-separated list of channel names from the list and nothing "
        "else. Do not explain.\n"
        f"Channels: {', '.join(sorted(available))}\n"
        "\n"
        f"Predicted impact class: {impact_class} (2 moderate, 3 major, 4 severe)\n"
        f"Cell coverage in the targeted divisions: "
        f"{'unknown' if cell_coverage_pct is None else f'{cell_coverage_pct:.0f}%'}\n"
        "\n"
        "Channels:"
    )

    try:
        answer = await call(prompt)
    except Exception as error:  # noqa: BLE001 - the deterministic mix is already complete
        _log.warning(
            "warning_channel_model_unavailable",
            error=type(error).__name__,
            impact="the deterministic channel matrix was used; the alert is unaffected",
        )
        return ()

    names = {token.strip().upper() for token in answer.replace("\n", ",").split(",")}
    return tuple(sorted(name for name in names if name in set(available)))
