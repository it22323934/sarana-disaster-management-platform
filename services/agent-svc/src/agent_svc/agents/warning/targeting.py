"""Who gets this warning, in which language, and who has already had one.

Three deterministic jobs. None of them reaches a model: who is in a division is a database
question, which language somebody reads is a stated preference, and whether they were
warned an hour ago is a timestamp. A model in any of those places would be a model
producing a targeting decision nobody could reproduce afterwards.

## Households with no channel are an output, not a drop

A household with no contact number is targeted, counted, and reported. They are the people
who need a vehicle with a loudhailer, and the number of them is the input to that decision.
Dropping them here would report a division as fully covered when part of it cannot be
reached at all - which is the precise failure `/delivery/gaps` exists to surface.

## Language never comes from a name

A household's stated `preferred_language` wins. With none stated, the order comes from the
**division's** dominant languages in reference data. Never from the person's name: it is
unreliable, and it is offensive when wrong in exactly the communities most likely to be
missed. That is the Ditwah failure - the 28 Nov 2025 press conference was Sinhala and
English only - reproduced by inference instead of by omission.

## Alert fatigue

A second watch-level alert to the same household for the same hazard event, inside the
window, is suppressed. An escalation is not: a household that had a watch and is now at
warning level is being told something new, and that is the message the whole system exists
to deliver.

Getting this backwards in either direction is a real harm. Suppress too much and somebody
misses the escalation. Suppress too little and by the third day of a cyclone people have
stopped reading, which is how the one that mattered gets ignored.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

import structlog

from agent_svc.agents.warning.ports import (
    DivisionReach,
    PriorAlert,
    WarningTarget,
)

_log = structlog.get_logger(__name__)

# The order languages are offered in when nothing else is known. Matches
# `alerting_svc.adapters.channels.base.languages_for`; a test asserts the two agree,
# because two different default orders would send two communities in one division
# different languages depending on which service made the decision.
DEFAULT_LANGUAGE_ORDER: Final[tuple[str, ...]] = ("si", "ta", "en")

# How long a household is considered recently warned about one hazard event.
#
# Six hours. Short enough that a genuinely new development inside a multi-day event still
# reaches people, long enough that a forecast regenerating every fifteen minutes does not
# send the same watch-level message twenty-four times before lunch.
FATIGUE_WINDOW_HOURS: Final = 6


@dataclass(frozen=True, slots=True)
class TargetPlan:
    """Who this alert goes to, and who was left out on purpose.

    The counts are what travel in the checkpoint; the targets themselves do not. A national
    fan-out is several hundred thousand rows, a checkpoint row stays under 64KB, and a
    checkpoint holds references rather than payloads. `dispatch` resolves them again from
    the directory in the same run.
    """

    targets: list[WarningTarget] = field(default_factory=list)
    suppressed: list[str] = field(default_factory=list)
    division_languages: dict[str, list[str]] = field(default_factory=dict)

    @property
    def reachable(self) -> list[WarningTarget]:
        return [target for target in self.targets if target.reachable]

    @property
    def no_channel(self) -> list[WarningTarget]:
        """The households nothing can reach. First-class output, never a silent drop."""
        return [target for target in self.targets if not target.reachable]

    def counts_by_division(self) -> dict[str, dict[str, int]]:
        """Per-division targeted and unreachable counts, for the checkpoint and the console."""
        counts: dict[str, dict[str, int]] = {}
        for target in self.targets:
            bucket = counts.setdefault(
                target.gn_division_code, {"targeted": 0, "no_channel_available": 0}
            )
            bucket["targeted"] += 1
            if not target.reachable:
                bucket["no_channel_available"] += 1
        return counts

    def as_summary(self) -> dict[str, int]:
        """The three numbers, always together. A count with no denominator is unactionable."""
        return {
            "targeted": len(self.targets),
            "no_channel_available": len(self.no_channel),
            "suppressed_for_fatigue": len(self.suppressed),
        }


def language_order(
    target: WarningTarget,
    *,
    reach: DivisionReach | None = None,
    default_order: tuple[str, ...] = DEFAULT_LANGUAGE_ORDER,
) -> list[str]:
    """Which languages to offer this household, most preferred first.

    The full order rather than one language: a channel that can carry three carries three,
    and one that can carry one takes the head of this list. Which channel can carry how
    many is alerting-svc's decision, not this agent's, so the ordering is produced whole.
    """
    if target.preferred_language:
        preferred = target.preferred_language
        return [preferred, *(code for code in default_order if code != preferred)]

    if reach and reach.dominant_languages:
        known = list(reach.dominant_languages)
        return [*known, *(code for code in default_order if code not in known)]

    return list(default_order)


def division_language_order(
    reach: dict[str, DivisionReach],
    codes: tuple[str, ...],
    *,
    default_order: tuple[str, ...] = DEFAULT_LANGUAGE_ORDER,
) -> dict[str, list[str]]:
    """The per-division language order, for the households that stated no preference.

    Handed to the dispatcher whole. A division with no reference entry gets the default
    order rather than being dropped: sending in the wrong order is recoverable, sending
    nothing is not.
    """
    ordered: dict[str, list[str]] = {}
    for code in codes:
        known = list(reach[code].dominant_languages) if code in reach else []
        ordered[code] = [*known, *(language for language in default_order if language not in known)]
    return ordered


def suppress_fatigued(
    targets: list[WarningTarget],
    priors: list[PriorAlert],
    *,
    impact_class: int,
) -> tuple[list[WarningTarget], list[str]]:
    """Drop households already warned at this level or higher for this hazard event.

    Returns the targets that survive and the household ids that did not.

    The comparison is `>=`, so an identical repeat is suppressed and an escalation is not.
    A household that had a class 2 watch and is now at class 3 gets the warning; one that
    had a class 3 warning and is now at class 3 again does not.

    `priors` is expected to be pre-filtered to the fatigue window by the caller, which is
    the only thing that needs a clock. Keeping this function pure is what lets the whole
    rule be tested against a fixed set of timestamps.
    """
    highest: dict[str, int] = {}
    for prior in priors:
        current = highest.get(prior.household_id)
        if current is None or prior.impact_class > current:
            highest[prior.household_id] = prior.impact_class

    kept: list[WarningTarget] = []
    suppressed: list[str] = []
    for target in targets:
        previous = highest.get(target.household_id)
        if previous is not None and previous >= impact_class:
            suppressed.append(target.household_id)
        else:
            kept.append(target)

    if suppressed:
        _log.info(
            "warning_targets_suppressed_for_fatigue",
            suppressed=len(suppressed),
            kept=len(kept),
            impact_class=impact_class,
            reason="already warned at this level or higher for this hazard event",
        )
    return kept, suppressed


def fatigue_window_start(now: datetime, *, hours: int = FATIGUE_WINDOW_HOURS) -> datetime:
    """The moment before which a prior alert no longer suppresses this one."""
    return now - timedelta(hours=hours)


def deduplicate(targets: list[WarningTarget]) -> list[WarningTarget]:
    """One message per handset.

    Two households sharing one phone - a common arrangement in a village - are one handset,
    and sending the same evacuation order to it twice is noise at the moment attention is
    scarcest. Unreachable households key on their own id and never collapse: each one is a
    separate person somebody has to go and find, and the gap figure has to say how many.
    """
    seen: dict[str, WarningTarget] = {}
    for target in targets:
        seen.setdefault(target.key, target)
    return list(seen.values())


def build_plan(
    targets: list[WarningTarget],
    *,
    reach: dict[str, DivisionReach],
    priors: list[PriorAlert],
    impact_class: int,
) -> TargetPlan:
    """Everything the targeting step decides, in one pass.

    Order matters and is not arbitrary. Deduplication runs before the fatigue check so two
    households on one handset are one decision rather than two; the fatigue check runs on
    what is left so the suppressed count means households rather than rows.
    """
    unique = deduplicate(targets)
    kept, suppressed = suppress_fatigued(unique, priors, impact_class=impact_class)

    codes = tuple(sorted({target.gn_division_code for target in kept}))
    languages = division_language_order(reach, codes)

    stated = Counter(
        target.preferred_language for target in kept if target.preferred_language
    )
    _log.info(
        "warning_targets_resolved",
        targeted=len(kept),
        no_channel=sum(1 for target in kept if not target.reachable),
        suppressed=len(suppressed),
        divisions=len(codes),
        stated_preferences=dict(stated),
    )

    return TargetPlan(targets=kept, suppressed=suppressed, division_languages=languages)
