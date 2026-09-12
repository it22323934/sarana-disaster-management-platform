"""What the warning graph needs from the outside world, as narrow protocols.

Five ports, and they exist for the same reason the forecast agent's three do: the whole
agent has to run against fakes. The claims this agent makes - that a quiet-hours watch
alert waits until six, that a second watch-level message to the same household is
suppressed and an escalation is not, that one dead channel does not take the other five
down with it - have to be tests, and a test needing Postgres, core-api, alerting-svc and a
telco gateway is one that runs in CI on a good day and nowhere else.

Each port is smaller than the client behind it. `AlertDispatcher` does not expose
alerting-svc; it exposes the two things this agent asks it to do. A port shaped like its
adapter leaks the adapter's problems into every test that stubs it.

## Nothing here carries a phone number

`WarningTarget.target_ref_hash` is an HMAC of the contact number, resolved to a real
address by the gateway at the edge. A `None` hash is a real and important answer - that
household cannot be messaged at all, and they are the people who need a vehicle with a
loudhailer rather than a retry. See `gaps.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

# `{gn_division_name}` - the same pattern `alerting_svc.domain.templates` parses bodies
# with. Duplicated rather than imported because agent-svc does not depend on alerting-svc,
# and a test asserts the two agree; a drift here would let this agent select a template it
# cannot actually fill.
PARAMETER_PATTERN: Final = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# The delivery vocabulary, mirroring `alerting.delivery_receipt.status`. A test asserts it
# matches alerting-svc's `DELIVERY_STATUSES` - a status this agent counts and the column
# rejects would fail at the INSERT, after the warning had already gone out.
DELIVERY_STATUSES: Final[tuple[str, ...]] = (
    "QUEUED",
    "SENT",
    "DELIVERED",
    "READ",
    "FAILED",
    "EXPIRED",
    "UNKNOWN",
    "NO_CHANNEL",
)

# What counts as the message having reached a handset. `UNKNOWN` is deliberately not here:
# a channel that cannot confirm has not confirmed, and rounding it up to delivered produces
# a map that says a village was warned when nobody knows whether it was.
CONFIRMED_STATUSES: Final[frozenset[str]] = frozenset({"SENT", "DELIVERED", "READ"})


@dataclass(frozen=True, slots=True)
class AlertTemplate:
    """One template from the catalogue, as this agent reads it.

    Only PUBLISHED templates ever reach here. A template becomes PUBLISHED when a named
    Sinhala reviewer and a named Tamil reviewer have each signed it (file 09), and this
    agent selects among reviewed text rather than producing any.
    """

    id: str
    code: str
    hazard_type: str
    severity: str
    urgency: str
    certainty: str
    body: dict[str, str]

    @property
    def parameters(self) -> frozenset[str]:
        """Every parameter the body references, across all three languages."""
        found: set[str] = set()
        for text in self.body.values():
            found |= set(PARAMETER_PATTERN.findall(text or ""))
        return frozenset(found)

    def render(self, values: dict[str, str]) -> dict[str, str]:
        """Substitute parameters into every language.

        Raises:
            KeyError: naming the first missing parameter. An alert must never dispatch
                reading "evacuate to {shelter_name}", so this refuses rather than leaving
                a placeholder in a life-safety message.
        """
        rendered: dict[str, str] = {}
        for language, text in self.body.items():
            filled = text or ""
            for name in PARAMETER_PATTERN.findall(filled):
                if name not in values:
                    raise KeyError(name)
                filled = filled.replace("{" + name + "}", values[name])
            rendered[language] = filled
        return rendered


@dataclass(frozen=True, slots=True)
class ForecastedDivision:
    """One GN division as the forecast left it.

    A projection of `hazard.impact_forecast`, not the row. The agent needs the class, the
    lead time and enough identity to target; it has no use for the drivers, and carrying a
    page of them through every checkpoint would cost every resume for nothing.
    """

    gn_division_id: str
    gn_division_code: str
    impact_class: int
    confidence: float = 0.0
    lead_time_hours: int = 0
    households: int = 0
    names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WarningTarget:
    """One household to warn, reduced to what a channel needs.

    Identified by an HMAC of the contact number, never the number. Nothing in this agent
    ever holds an address, which is what makes an agent-svc checkpoint dump uninteresting.
    """

    household_id: str
    gn_division_code: str
    target_ref_hash: str | None = None
    preferred_language: str | None = None

    @property
    def reachable(self) -> bool:
        """Whether this household can be messaged at all.

        The question to branch on. Not everybody has a phone; `False` is a fact about a
        person that belongs in the gap report, not a failure to retry.
        """
        return bool(self.target_ref_hash)

    @property
    def key(self) -> str:
        """What the delivery accounting counts by.

        The contact hash, so two households sharing one handset - a common arrangement in
        a village - are one phone and get one message. An unreachable household keys on
        its own id instead, so they never collapse: each one is a separate person somebody
        has to go and find, and the gap figure has to say how many.
        """
        return self.target_ref_hash or f"unreachable:{self.household_id}"


@dataclass(frozen=True, slots=True)
class DivisionReach:
    """What is known about reaching one division, before anything is sent.

    `dominant_languages` is the division's, from reference data. It is what language
    routing falls back to when a household has stated no preference - never the person's
    name, which is unreliable and goes wrong in exactly the communities most likely to be
    missed.
    """

    gn_division_code: str
    cell_coverage_pct: float | None = None
    dominant_languages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PriorAlert:
    """An alert already sent to one household for one hazard event.

    What alert fatigue is measured against. Carries the impact class it went out at,
    because an escalation is new information and a repeat is not.
    """

    household_id: str
    hazard_event_id: str
    impact_class: int
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class Receipt:
    """What one channel reports about one message."""

    target_key: str
    channel: str
    language: str
    status: str
    provider_ref: str | None = None
    failure_reason: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.status in CONFIRMED_STATUSES


@dataclass(frozen=True, slots=True)
class ChannelOutcome:
    """Everything one channel did, including having failed entirely.

    `error` set means the channel never ran. That is different from every message failing:
    one is an integration this platform could not use, the other is a set of handsets that
    were tried and did not answer, and the gap report says which.
    """

    channel: str
    receipts: list[Receipt] = field(default_factory=list)
    error: str | None = None

    @property
    def failed_outright(self) -> bool:
        return self.error is not None


@dataclass(frozen=True, slots=True)
class DispatchOrder:
    """What the agent asks alerting-svc to send.

    Rendered text, resolved targets, chosen channels and the language routing. Everything
    is decided by the time this is built; the dispatcher decides nothing.
    """

    hazard_event_id: str
    template_code: str
    template_id: str
    body: dict[str, str]
    parameters: dict[str, str]
    gn_division_ids: tuple[str, ...]
    gn_division_codes: tuple[str, ...]
    channels: tuple[str, ...]
    division_languages: dict[str, list[str]]
    effective_at: datetime
    expires_at: datetime
    targets: list[WarningTarget]
    free_text: dict[str, str] | None = None
    correlation_id: str = ""


class ForecastSource(Protocol):
    """Where the impact forecast this alert is written against comes from."""

    async def current(self, *, hazard_event_id: str) -> list[ForecastedDivision]:
        """The forecast rows in force for this hazard event, newest generation only.

        Newest only, and that is the whole contract. `hazard.impact_forecast` is never
        updated - a new run writes new rows - so a source returning everything it finds
        would hand this agent a division at class 2 from six hours ago alongside the same
        division at class 4 from ten minutes ago, and the alert would go out against
        whichever the sort happened to put first.
        """
        ...


class TemplateCatalogue(Protocol):
    """The published catalogue this agent selects from."""

    async def published(self, *, hazard_type: str | None = None) -> list[AlertTemplate]:
        """Every PUBLISHED template, optionally narrowed to one hazard.

        Raises:
            Exception: if the catalogue cannot be read. Never an empty list for an outage -
                an empty catalogue means "no template fits", which routes to an operator,
                and an outage dressed up as that would put a false question in front of
                somebody during a cyclone.
        """
        ...


class TargetDirectory(Protocol):
    """Who is in a division, and what is known about reaching them."""

    async def targets_in(self, gn_division_codes: tuple[str, ...]) -> list[WarningTarget]:
        """Every household in these divisions, reachable or not.

        Households with no contact number are included with no hash. Dropping them here
        would report a division as fully covered when part of it cannot be reached at all,
        which is the precise failure the gap report exists to surface.
        """
        ...

    async def reach(self, gn_division_codes: tuple[str, ...]) -> dict[str, DivisionReach]:
        """Coverage and dominant languages, per division."""
        ...


class AlertHistory(Protocol):
    """What has already been sent, for the fatigue check."""

    async def recent(self, *, hazard_event_id: str, since: datetime) -> list[PriorAlert]:
        """Alerts sent for this hazard event since a moment, per household."""
        ...


class AlertDispatcher(Protocol):
    """Where an alert goes to actually be sent."""

    async def dispatch(self, order: DispatchOrder) -> list[ChannelOutcome]:
        """Fan out over the chosen channels, and report what each one did.

        Must not raise for one channel's failure - that is a `ChannelOutcome` carrying an
        error. A warning that reached five channels and failed on the sixth is a warning
        that reached five channels.
        """
        ...

    async def receipts(self, *, alert_key: str) -> list[Receipt]:
        """Receipts as they stand now, including the ones a DLR has since upgraded."""
        ...


class ModelCall(Protocol):
    """One model call: a prompt in, text out.

    This narrow because both places this agent uses a model want exactly this, and because
    a port that exposed the client would make every degraded-path test construct one.
    """

    async def __call__(self, prompt: str) -> str: ...


def as_division(raw: dict[str, Any]) -> ForecastedDivision:
    """One forecast row, as it arrives from the store or an event payload."""
    return ForecastedDivision(
        gn_division_id=str(raw["gn_division_id"]),
        gn_division_code=str(raw["gn_division_code"]),
        impact_class=int(raw["impact_class"]),
        confidence=float(raw.get("confidence") or 0.0),
        lead_time_hours=int(raw.get("lead_time_hours") or 0),
        households=int(raw.get("households") or raw.get("expected_households_affected") or 0),
        names=dict(raw.get("names") or {}),
    )
