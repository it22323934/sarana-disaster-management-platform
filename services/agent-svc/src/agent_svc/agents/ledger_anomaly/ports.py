"""What the anomaly graph needs from the outside world, and what it deliberately cannot get.

## There is no port that returns an officer

Read ADR-009 before changing anything here. The single most important property of this agent
is that officer identity is **not a feature** — not directly, and not as a proxy. So
`Assessment` carries no assessor id, no approver id and no user id, and there is no port
through which one could be fetched.

That is stronger than a rule saying "do not use it". A rule can be forgotten by whoever adds
the next detector; a field that does not exist cannot be read. If a future detector genuinely
needs to distinguish two assessments made by different people, adding that field is a
deliberate act somebody has to argue for against this docstring and against a database CHECK
that rejects a rationale containing a user id at any depth.

**The proxy is the trap.** "Assessments per assessor" is officer identity wearing a
statistic's clothes. The unit of analysis is the **GN division per day**, everywhere, and
`Assessment.gn_division_code` is what every detector groups on.

## The exposure port is what makes the whole agent defensible

A division that was genuinely hit hardest *should* produce higher, more numerous and faster
assessments. Comparing it against a national average would flag it for having been damaged.
`ExposureSource` supplies what the impact forecast predicted for that division, and every
detector normalises against that rather than against its peers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# What a flag can be about. Mirrors `aid.anomaly_flag.subject_type`; a test asserts they
# agree, because a subject the column rejects would fail at the INSERT after a reviewer had
# already been notified.
ANOMALY_SUBJECTS: tuple[str, ...] = (
    "ASSESSMENT",
    "ENTITLEMENT",
    "DISBURSEMENT",
    "GN_DIVISION",
    "COST_SCHEDULE",
)

# The damage categories an assessment can be against. Mirrors `aid.assessment.category`.
DAMAGE_CATEGORIES: tuple[str, ...] = (
    "HOUSE_FULL",
    "HOUSE_PARTIAL",
    "HOUSEHOLD_GOODS",
    "LIVELIHOOD_TOOLS",
    "CROP",
    "LIVESTOCK",
    "FISHING_GEAR",
    "DEATH",
    "INJURY",
)


@dataclass(frozen=True, slots=True)
class Assessment:
    """One damage assessment, reduced to what a detector may see.

    **No assessor, no approver, no user id.** See the module docstring: the omission is the
    safeguard, and it is deliberate that this dataclass would need editing before any
    detector could group by person.

    `household_id` is present because the duplicate-household detector needs it, and it
    identifies a household rather than an officer. `evidence_hashes` are perceptual hashes
    of photographs, not the photographs.
    """

    assessment_id: str
    gn_division_code: str
    ds_division_code: str
    district_code: str
    household_id: str
    category: str
    assessed_value_lkr: int
    assessed_at: datetime

    approved_at: datetime | None = None
    citizen_confirmed: bool | None = None
    lon: float | None = None
    lat: float | None = None
    evidence_hashes: tuple[str, ...] = ()

    @property
    def approval_minutes(self) -> float | None:
        """How long from assessment to approval, or None if not yet approved."""
        if self.approved_at is None:
            return None
        return max(0.0, (self.approved_at - self.assessed_at).total_seconds() / 60.0)


@dataclass(frozen=True, slots=True)
class DivisionContext:
    """What is known about a division, independently of who assessed it.

    Every field here is a fact about the place: what the forecast predicted, how much of it
    a phone signal reaches, what its housing stock looks like. None of it is a fact about a
    person, and that is what makes it safe to normalise against.
    """

    gn_division_code: str

    # From `hazard.impact_forecast`. The whole basis of the normalisation.
    impact_class: int = 0
    expected_households_affected: int = 0
    forecast_confidence: float = 0.0

    # From `admin.gn_division`. `cell_coverage_pct` is what `confirmation_gap` must join
    # against before it fires - a division at 35% coverage with 40% confirmation is a
    # coverage problem, not a question about anybody.
    household_count: int = 0
    cell_coverage_pct: float | None = None

    # The share of housing that is permanent construction, where one exists. Housing stock
    # is why two divisions legitimately differ in category mix, and `category_drift` reads
    # it before deciding anything is unusual.
    permanent_housing_pct: float | None = None

    @property
    def surveyed(self) -> bool:
        """Whether there is a forecast to normalise against at all.

        A division with no forecast cannot be normalised, and a detector that fired on one
        would be comparing it against nothing. `normalisation` suppresses instead.
        """
        return self.forecast_confidence > 0.0


@dataclass(frozen=True, slots=True)
class Evidence:
    """One fact that contributed to a detector's score.

    Deliberately a value and a comparison, never a conclusion. "median approval 3 minutes
    against a district median of 47" is evidence; "approvals are suspiciously fast" is a
    finding, and this agent does not produce findings.
    """

    label: str
    value: float | str
    compared_with: float | str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "value": self.value,
            "compared_with": self.compared_with,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Signal:
    """What one detector found in one division.

    `ruled_out` is not optional decoration. Build file 17: "a flag that does not show what
    was ruled out is not actionable and gets suppressed." A reviewer opening a flag needs to
    see which innocent explanations were already checked, or they start from zero and the
    flag costs more than it saves.
    """

    detector: str
    gn_division_code: str
    score: float
    evidence: list[Evidence] = field(default_factory=list)
    ruled_out: list[str] = field(default_factory=list)
    subject_type: str = "GN_DIVISION"

    @property
    def actionable(self) -> bool:
        """Whether this signal is fit to become a flag."""
        return bool(self.evidence) and bool(self.ruled_out)

    def as_rationale(self) -> dict[str, Any]:
        """The `aid.anomaly_flag.rationale` document.

        A JSONB object, as the column's CHECK requires, and one the database will reject if
        it contains a user id at any depth - which is the last line of defence behind this
        agent's own post-check.
        """
        return {
            "detector": self.detector,
            "gn_division_code": self.gn_division_code,
            "score": round(self.score, 4),
            "evidence": [item.as_dict() for item in self.evidence],
            "innocent_explanations_ruled_out": list(self.ruled_out),
        }


@dataclass(frozen=True, slots=True)
class Flag:
    """A pattern that warrants review. Never a finding, never about a person."""

    detector: str
    detector_version: str
    subject_type: str
    subject_id: str
    score: float
    rationale: dict[str, Any]
    priority: str = "low"
    context_available: bool = True


class AssessmentSource(Protocol):
    """The assessments in scope for one run."""

    async def batch(
        self, *, district_code: str | None = None, since: datetime | None = None
    ) -> list[Assessment]:
        """Every assessment in the window.

        Raises rather than returning an empty list when unreachable. An empty batch and an
        unreachable database both produce zero flags, and only one of them means nothing
        was found.
        """
        ...


class ExposureSource(Protocol):
    """What the forecast predicted for each division, and what the division is like."""

    async def context_for(self, gn_division_codes: tuple[str, ...]) -> dict[str, DivisionContext]:
        """Division context, keyed by code.

        A division missing from the result has no forecast and is not normalisable. That is
        a real state - the forecast covers warned districts, not the country - and
        `normalisation` suppresses rather than falling back to a national comparison.
        """
        ...


class FlagStore(Protocol):
    """Where a flag is written, and where its disposition is read back."""

    async def raise_flags(self, flags: list[Flag]) -> list[str]:
        """Insert flags in OPEN and return their ids.

        OPEN and nothing else. A flag this agent could write already dispositioned would be
        a flag that skipped the human review ADR-009 requires.
        """
        ...

    async def disposition_rates(
        self, *, since: datetime | None = None
    ) -> dict[str, dict[str, int]]:
        """Disposition counts per detector, for the false-positive rate.

        The number ADR-009 makes first-class. A detection rate without it is a number
        designed to impress rather than inform.
        """
        ...


class ModelCall(Protocol):
    """One model call: a prompt in, text out. Used only to contextualise a signal."""

    async def __call__(self, prompt: str) -> str: ...
