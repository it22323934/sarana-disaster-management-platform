"""Fakes for the warning agent's five ports.

Everything the agent talks to, small enough to configure in a line and honest about the
failure modes that matter: a channel that fails outright, a directory holding households
with no phone, a catalogue mid-review with a gap in it.

The fakes record what they were asked, because several of the claims being tested are about
what the agent *did not* do - did not send at 2 a.m., did not message a household warned an
hour ago, did not fall back to a weaker template - and a test can only assert that against
something that remembers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from agent_svc.agents.warning.ports import (
    AlertTemplate,
    ChannelOutcome,
    DispatchOrder,
    DivisionReach,
    ForecastedDivision,
    PriorAlert,
    Receipt,
    WarningTarget,
)

# A fixed instant, in the middle of the working day in Colombo, so the quiet-hours rule is
# not in play unless a test asks for it. 09:30 Colombo is 04:00 UTC.
NOON_COLOMBO = datetime(2026, 11, 28, 4, 0, tzinfo=UTC)

# 02:00 Colombo the same night: 20:30 UTC the day before.
NIGHT_COLOMBO = datetime(2026, 11, 27, 20, 30, tzinfo=UTC)


def template(
    code: str,
    *,
    hazard: str = "FLOOD",
    severity: str = "SEVERE",
    body: str = "{gn_division_name}",
) -> AlertTemplate:
    """One published template. The three bodies differ so a test can tell them apart."""
    return AlertTemplate(
        id=f"tpl-{code}",
        code=code,
        hazard_type=hazard,
        severity=severity,
        urgency="IMMEDIATE",
        certainty="LIKELY",
        body={
            "si": f"[si] {body}",
            "ta": f"[ta] {body}",
            "en": f"[en] {body}",
        },
    )


SEEDED_CATALOGUE = [
    template("FLOOD_WATCH", severity="MODERATE"),
    template("FLOOD_WARNING", severity="SEVERE"),
    template(
        "FLOOD_EVACUATE_IMMEDIATE",
        severity="EXTREME",
        body="{gn_division_name} {shelter_name}",
    ),
    template("LANDSLIDE_WATCH", hazard="LANDSLIDE", severity="MODERATE"),
    template("LANDSLIDE_WARNING", hazard="LANDSLIDE", severity="SEVERE"),
    template("CYCLONE_WARNING", hazard="CYCLONE", severity="EXTREME"),
]


@dataclass
class FakeForecasts:
    """The forecast rows a run is written against."""

    divisions: list[ForecastedDivision] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)

    async def current(self, *, hazard_event_id: str) -> list[ForecastedDivision]:
        self.asked.append(hazard_event_id)
        return list(self.divisions)


@dataclass
class FakeCatalogue:
    """The published catalogue, optionally with a gap in it."""

    templates: list[AlertTemplate] = field(default_factory=lambda: list(SEEDED_CATALOGUE))

    async def published(self, *, hazard_type: str | None = None) -> list[AlertTemplate]:
        if hazard_type is None:
            return list(self.templates)
        return [t for t in self.templates if t.hazard_type.upper() == hazard_type.upper()]


@dataclass
class FakeDirectory:
    """Households and division coverage."""

    targets: list[WarningTarget] = field(default_factory=list)
    coverage: dict[str, float | None] = field(default_factory=dict)
    languages: dict[str, tuple[str, ...]] = field(default_factory=dict)
    calls: int = 0

    async def targets_in(self, gn_division_codes: tuple[str, ...]) -> list[WarningTarget]:
        self.calls += 1
        wanted = set(gn_division_codes)
        return [target for target in self.targets if target.gn_division_code in wanted]

    async def reach(self, gn_division_codes: tuple[str, ...]) -> dict[str, DivisionReach]:
        return {
            code: DivisionReach(
                gn_division_code=code,
                cell_coverage_pct=self.coverage.get(code),
                dominant_languages=self.languages.get(code, ()),
            )
            for code in gn_division_codes
        }


@dataclass
class FakeHistory:
    """What has already gone out, for the fatigue check."""

    priors: list[PriorAlert] = field(default_factory=list)

    async def recent(self, *, hazard_event_id: str, since: datetime) -> list[PriorAlert]:
        return [
            prior
            for prior in self.priors
            if prior.hazard_event_id == hazard_event_id and prior.sent_at >= since
        ]


@dataclass
class FakeDispatcher:
    """A dispatcher that reports per-channel outcomes and remembers every order.

    `dead_channels` fail outright - they never ran at all, which is the case the gap report
    has to distinguish from every message failing. `unconfirmable` return UNKNOWN, which
    counts against coverage rather than for it.
    """

    dead_channels: frozenset[str] = frozenset()
    unconfirmable: frozenset[str] = frozenset()
    orders: list[DispatchOrder] = field(default_factory=list)
    _receipts: dict[str, list[Receipt]] = field(default_factory=dict)

    async def dispatch(self, order: DispatchOrder) -> list[ChannelOutcome]:
        self.orders.append(order)
        outcomes: list[ChannelOutcome] = []
        produced: list[Receipt] = []

        for channel in order.channels:
            if channel in self.dead_channels:
                outcomes.append(ChannelOutcome(channel=channel, error="gateway unreachable"))
                continue
            receipts = [
                Receipt(
                    target_key=target.key,
                    channel=channel,
                    language=order.division_languages.get(target.gn_division_code, ["en"])[0],
                    status=_status_for(target, channel, self.unconfirmable),
                )
                for target in order.targets
            ]
            produced.extend(receipts)
            outcomes.append(ChannelOutcome(channel=channel, receipts=receipts))

        self._receipts[order.template_code] = produced
        self._receipts["_last"] = produced
        return outcomes

    async def receipts(self, *, alert_key: str) -> list[Receipt]:
        return list(self._receipts.get("_last", []))


def _status_for(target: WarningTarget, channel: str, unconfirmable: frozenset[str]) -> str:
    if not target.reachable:
        return "NO_CHANNEL"
    if channel in unconfirmable:
        return "UNKNOWN"
    return "DELIVERED"


def division(
    code: str,
    *,
    impact_class: int = 3,
    households: int = 100,
    name: str = "Gampola",
) -> ForecastedDivision:
    return ForecastedDivision(
        gn_division_id=f"id-{code}",
        gn_division_code=code,
        impact_class=impact_class,
        confidence=0.8,
        lead_time_hours=24,
        households=households,
        names={"en": name, "si": name, "ta": name},
    )


def household(
    number: int, code: str, *, reachable: bool = True, language: str | None = None
) -> WarningTarget:
    return WarningTarget(
        household_id=f"hh-{number}",
        gn_division_code=code,
        target_ref_hash=f"hash-{number}" if reachable else None,
        preferred_language=language,
    )


@pytest.fixture
def catalogue() -> FakeCatalogue:
    return FakeCatalogue()


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


@pytest.fixture
def directory() -> FakeDirectory:
    return FakeDirectory(
        targets=[household(index, "LK-21-01-001") for index in range(1, 11)],
        coverage={"LK-21-01-001": 85.0},
    )


class RecordingCall:
    """A model stand-in that answers with a fixed string and remembers the prompts."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


class BrokenCall:
    """A model provider that is down. Every agent must work without one."""

    async def __call__(self, prompt: str) -> str:
        raise ConnectionError("the model provider is unreachable")


def state_input(**values: Any) -> dict[str, Any]:
    """The `output` dict a run starts with."""
    return dict(values)
