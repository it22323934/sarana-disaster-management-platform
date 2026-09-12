"""Fixtures for the anomaly agent.

`division()` builds a whole division's assessments from a shape rather than row by row,
because the interesting thing about every test here is the *shape* — how many, how valuable,
how fast, how confirmed — and a wall of literal rows would bury it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agent_svc.agents.ledger_anomaly.ports import Assessment, DivisionContext, Flag

NOW = datetime(2026, 12, 5, 4, 0, tzinfo=UTC)

SEVERE = "LK-21-01-001"
MILD = "LK-21-01-002"


def division(
    code: str = SEVERE,
    *,
    count: int = 20,
    total_loss_share: float = 0.1,
    approval_minutes: float = 60.0,
    confirmed_share: float | None = None,
    burst: bool = False,
    household_prefix: str | None = None,
    evidence: tuple[str, ...] = (),
    spread_lon: float = 0.0,
) -> list[Assessment]:
    """One division's assessments, described by shape.

    `household_prefix` shared across two calls makes the same households appear twice,
    which is what the duplicate detector looks for. `spread_lon` scatters the coordinates,
    which is what the geo detector looks for.
    """
    prefix = household_prefix or code
    rows: list[Assessment] = []
    for index in range(count):
        is_total = index < round(count * total_loss_share)
        offset = timedelta(minutes=index * 2) if burst else timedelta(minutes=index * 25)
        assessed = NOW + offset
        rows.append(
            Assessment(
                assessment_id=f"a-{code}-{index}-{len(evidence)}",
                gn_division_code=code,
                ds_division_code=code.rsplit("-", 1)[0],
                district_code=code.rsplit("-", 2)[0],
                household_id=f"hh-{prefix}-{index}",
                category="HOUSE_FULL" if is_total else "HOUSEHOLD_GOODS",
                assessed_value_lkr=500_000 if is_total else 40_000,
                assessed_at=assessed,
                approved_at=assessed + timedelta(minutes=approval_minutes),
                citizen_confirmed=(
                    None if confirmed_share is None else index < round(count * confirmed_share)
                ),
                lon=80.5 + (index * spread_lon),
                lat=7.1,
                evidence_hashes=evidence,
            )
        )
    return rows


def context(
    code: str = SEVERE,
    *,
    impact_class: int = 4,
    households: int = 400,
    expected_affected: int = 0,
    coverage: float | None = 95.0,
    permanent_housing: float | None = None,
    forecast_confidence: float = 0.8,
) -> DivisionContext:
    return DivisionContext(
        gn_division_code=code,
        impact_class=impact_class,
        expected_households_affected=expected_affected,
        forecast_confidence=forecast_confidence,
        household_count=households,
        cell_coverage_pct=coverage,
        permanent_housing_pct=permanent_housing,
    )


@dataclass
class FakeAssessments:
    batch_rows: list[Assessment] = field(default_factory=list)

    async def batch(self, **kwargs: Any) -> list[Assessment]:
        return list(self.batch_rows)


@dataclass
class FakeExposure:
    divisions: dict[str, DivisionContext] = field(default_factory=dict)

    async def context_for(self, gn_division_codes: tuple[str, ...]) -> dict[str, DivisionContext]:
        return {code: self.divisions[code] for code in gn_division_codes if code in self.divisions}


@dataclass
class FakeFlagStore:
    """Records what was raised.

    Has no way to disposition a flag: the agent must not be able to close its own, and a
    fake that offered it would let a test pass that the real system would refuse.
    """

    raised: list[Flag] = field(default_factory=list)
    rates: dict[str, dict[str, int]] = field(default_factory=dict)

    async def raise_flags(self, flags: list[Flag]) -> list[str]:
        self.raised.extend(flags)
        return [f"flag-{index}" for index, _ in enumerate(flags)]

    async def disposition_rates(self, **kwargs: Any) -> dict[str, dict[str, int]]:
        return dict(self.rates)


class RecordingCall:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answer


class BrokenCall:
    async def __call__(self, prompt: str) -> str:
        raise ConnectionError("the model provider is unreachable")


# A model answer that is safe, complete and usable. Reused wherever a test needs the
# contextualiser to succeed rather than to be the thing under test.
GOOD_CONTEXT = (
    '{"pattern_summary": "Assessment values in this division cluster at total loss more '
    'often than the forecast predicted.", "innocent_explanations": ["the survey may have '
    'covered the worst-affected streets first"], "what_would_resolve_it": ["compare '
    'against the DS survey for the same period"], "suggested_priority": "medium", '
    '"confidence": 0.6}'
)


@pytest.fixture
def store() -> FakeFlagStore:
    return FakeFlagStore()
