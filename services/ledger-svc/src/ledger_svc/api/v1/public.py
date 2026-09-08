"""The aggregates the public transparency dashboard reads. No authentication, anywhere.

Build file 10 published the per-entry feed, the anchors and the cost schedules - the three
things a verifier needs. This module publishes the three things a *reader* needs: the
funnel from assessed damage to money confirmed received, the same figures per district, and
one district broken down to DS division.

Separate from `ledger.py` for one reason worth stating. Everything in that module is
either inside the hash chain or is the chain's own metadata, and a change to it changes
what an outside verifier recomputes. Nothing here is hashed or verifiable; it is derived
presentation over the same rows. Keeping them apart means a dashboard requirement can
never quietly alter the shape a verifier depends on.

Three rules run through all of it:

**Nothing is grouped below DS division.** GN division is the level at which a
four-household hamlet with one disbursement identifies a family by arithmetic, and the
brief's own privacy floor would suppress nearly every GN cell in this seed anyway - leaving
only the largest divisions, which is a biased sample published as though it were the
picture.

**Suppression is disclosed, never silent.** A withheld row comes back as a count and a
reason. Silent omission looks like missing data and invites the wrong conclusion, which is
the opposite of what a transparency surface is for.

**The uncomfortable figures carry the same weight as the good ones.** `unconfirmed`,
`disputed` and `reversed` are their own fields with their own denominators, at the same
level of the response as `disbursed`. A response shape that made them optional or nested
would be the first step towards a page that buries them.
"""

from __future__ import annotations

import re
from typing import Any, Final

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.api.deps import PublicSessionDep
from ledger_svc.domain.suppression import MIN_CELL_SIZE, apply_minimum_cell_size
from ledger_svc.repo import queries
from sarana_shared.domain.time import utc_now
from sarana_shared.errors import ValidationFailed

router = APIRouter(prefix="/public", tags=["public"])

# The privacy floor is defined in `domain.suppression` and imported, not restated. Two
# copies of a policy number is one copy that gets lowered without the other noticing.

# `LK-21`. Anchored, because an unanchored pattern would let `21` match and the LIKE built
# from it would scan the whole table.
_DISTRICT_CODE = re.compile(r"^LK-\d{2}$")

SUPPRESSION_NOTE: Final = (
    f"A DS division with between 1 and {MIN_CELL_SIZE - 1} disbursements in this period is "
    "withheld: at that size the amount and the division together can identify a household. "
    "Withheld divisions are counted in `suppressed_divisions` and their money is counted in "
    "`suppressed_lkr_cents`, so the district total below still adds up. A division with no "
    "disbursements at all is not suppressed - it is published as a zero, because 'nothing "
    "was paid here' is the finding a reader most needs."
)


class FunnelStage(BaseModel):
    """One stage of the funnel: an amount, a count, and what it is a fraction of.

    `of_previous` is a fraction rather than a formatted percentage because the three
    locales format numbers differently and the render boundary is the only place that
    should decide. It is null on the first stage, which has nothing above it - not zero,
    which would read as "0% of something".
    """

    model_config = ConfigDict(frozen=True)

    lkr_cents: int
    count: int
    of_previous: float | None = Field(
        default=None, description="This stage's amount over the previous stage's, 0 to 1."
    )


class PublicFunnel(BaseModel):
    """Assessed, approved, disbursed, confirmed - and everything that went wrong.

    The failure figures are siblings of the success ones and not a nested `problems`
    object, because the response shape is the first thing that decides whether a page can
    bury them.
    """

    model_config = ConfigDict(frozen=True)

    assessed: FunnelStage
    approved: FunnelStage
    disbursed: FunnelStage
    confirmed: FunnelStage

    unconfirmed_count: int = Field(
        description="Released, past the reply window, and the household never answered. "
        "Not a failure count: no reply means a dead handset, an SMS that never arrived, or "
        "a message nobody understood, none of which is evidence the money is missing."
    )
    awaiting_reply_count: int = Field(
        description="Released inside the reply window. Still too early to call."
    )
    reversed_count: int
    reversed_lkr_cents: int = Field(
        description="Released and returned by the bank. Counted inside `disbursed` and "
        "reported again here, because the state did believe it had paid and the "
        "compensating entry is the honest correction rather than a quiet subtraction."
    )

    households: int = Field(description="Distinct households with an accepted assessment.")
    gn_divisions: int = Field(description="Distinct GN divisions with an accepted assessment.")

    grievance_count: int
    grievance_open_count: int

    last_disbursement_at: str | None
    last_anchor_date: str | None
    last_seq: int | None
    as_of: str = Field(description="When this response was computed. ISO 8601 UTC.")
    confirmation_window_days: int


class DistrictMetrics(BaseModel):
    """One district, every metric the choropleth can colour by.

    `median_days_to_disbursement` is the metric the brief singles out and it is a median
    rather than a mean: the distribution has a long tail, and one household waiting ninety
    days pulls an average far enough that the figure stops describing anyone's experience.

    Null means the district has disbursed nothing, which is not the same as zero days and
    must not colour as though it were fast.
    """

    model_config = ConfigDict(frozen=True)

    district_code: str
    assessed_count: int
    assessed_households: int
    assessed_divisions: int
    assessed_lkr_cents: int
    approved_count: int
    approved_lkr_cents: int
    disbursed_count: int
    disbursed_lkr_cents: int
    confirmed_count: int
    reversed_count: int
    confirmation_rate: float | None
    median_days_to_disbursement: float | None
    disbursed_per_household_lkr_cents: int | None
    grievance_count: int
    grievance_open_count: int
    grievance_rate_per_1000_disbursements: float | None
    median_grievance_resolution_days: float | None
    last_released_at: str | None


class DistrictMetricsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    districts: list[DistrictMetrics]
    as_of: str
    note: str


class DSDivisionRow(BaseModel):
    """One DS division inside a district. Published only above the privacy floor."""

    model_config = ConfigDict(frozen=True)

    ds_division_code: str
    assessed_count: int
    assessed_households: int
    assessed_divisions: int
    assessed_lkr_cents: int
    approved_count: int
    approved_lkr_cents: int
    disbursed_count: int
    disbursed_lkr_cents: int
    confirmed_count: int
    median_days_to_disbursement: float | None


class DistrictDetail(BaseModel):
    """One district by DS division, with what was withheld stated rather than omitted."""

    model_config = ConfigDict(frozen=True)

    district_code: str
    divisions: list[DSDivisionRow]
    suppressed_divisions: int = Field(
        description="DS divisions withheld for being below the minimum cell size."
    )
    suppressed_disbursements: int
    suppressed_lkr_cents: int
    minimum_cell_size: int
    suppression_note: str
    totals: DSDivisionRow = Field(
        description="The district total, including the suppressed rows. Published so the "
        "withheld money is still visible in aggregate and the columns add up."
    )
    as_of: str


DISTRICT_NOTE: Final = (
    "Administrative area codes, not names. Resolve them against "
    "GET /api/v1/public/areas/districts on core-api. A district with assessments and no "
    "disbursements is published as zeroes rather than omitted, because that is the finding."
)


def _fraction(numerator: int, denominator: int) -> float | None:
    """A ratio, or null when there is nothing to divide by.

    Null rather than zero throughout this module. Zero is a measured result; null is the
    absence of one, and a choropleth that renders "no data" as the best possible value is
    the specific way this page would mislead.
    """
    return round(numerator / denominator, 4) if denominator else None


def _seconds_to_days(seconds: Any) -> float | None:
    return round(float(seconds) / 86_400, 1) if seconds is not None else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _now_iso() -> str:
    return utc_now().isoformat()


@router.get("/funnel", response_model=PublicFunnel)
async def public_funnel(session: PublicSessionDep) -> Any:
    """The four headline numbers, each with its denominator. No authentication.

    Every figure comes from one statement, so a reader comparing approved against assessed
    is comparing one instant. Two queries a second apart could publish a stage larger than
    the one above it, and a transparency page that shows 101% has spent its credibility on
    a race condition.
    """
    row = await queries.public_funnel(session)
    counts = await queries.confirmation_rate(session, window_days=_confirmation_window())

    assessed = int(row["assessed_lkr_cents"] or 0)
    approved = int(row["approved_lkr_cents"] or 0)
    disbursed = int(row["disbursed_lkr_cents"] or 0)
    confirmed = int(row["confirmed_lkr_cents"] or 0)

    return {
        "assessed": {
            "lkr_cents": assessed,
            "count": int(row["assessed_count"] or 0),
            "of_previous": None,
        },
        "approved": {
            "lkr_cents": approved,
            "count": int(row["approved_count"] or 0),
            "of_previous": _fraction(approved, assessed),
        },
        "disbursed": {
            "lkr_cents": disbursed,
            "count": int(row["disbursed_count"] or 0),
            "of_previous": _fraction(disbursed, approved),
        },
        "confirmed": {
            "lkr_cents": confirmed,
            "count": int(row["confirmed_count"] or 0),
            "of_previous": _fraction(confirmed, disbursed),
        },
        "unconfirmed_count": int(counts["unconfirmed"] or 0),
        "awaiting_reply_count": int(counts["awaiting"] or 0),
        "reversed_count": int(row["reversed_count"] or 0),
        "reversed_lkr_cents": int(row["reversed_lkr_cents"] or 0),
        "households": int(row["assessed_households"] or 0),
        "gn_divisions": int(row["assessed_divisions"] or 0),
        "grievance_count": int(row["grievance_count"] or 0),
        "grievance_open_count": int(row["grievance_open_count"] or 0),
        "last_disbursement_at": _iso(row["last_disbursement_at"]),
        "last_anchor_date": row["last_anchor_date"],
        "last_seq": row["last_seq"],
        "as_of": _now_iso(),
        "confirmation_window_days": _confirmation_window(),
    }


@router.get("/districts", response_model=DistrictMetricsResponse)
async def public_districts(session: PublicSessionDep) -> Any:
    """Every district, every metric the map can colour by. No authentication.

    District is the finest grain published without a drill, and it is not a privacy floor
    here - twenty-five districts of hundreds of thousands of households each re-identify
    nobody. The floor applies one level down, in `/districts/{code}`.
    """
    rows = await queries.public_district_metrics(session)

    districts = []
    for row in rows:
        disbursed_count = int(row["disbursed_count"] or 0)
        assessed_households = int(row["assessed_households"] or 0)
        disbursed_cents = int(row["disbursed_lkr_cents"] or 0)
        districts.append(
            {
                "district_code": row["district_code"],
                "assessed_count": int(row["assessed_count"] or 0),
                "assessed_households": assessed_households,
                "assessed_divisions": int(row["assessed_divisions"] or 0),
                "assessed_lkr_cents": int(row["assessed_lkr_cents"] or 0),
                "approved_count": int(row["approved_count"] or 0),
                "approved_lkr_cents": int(row["approved_lkr_cents"] or 0),
                "disbursed_count": disbursed_count,
                "disbursed_lkr_cents": disbursed_cents,
                "confirmed_count": int(row["confirmed_count"] or 0),
                "reversed_count": int(row["reversed_count"] or 0),
                "confirmation_rate": _fraction(int(row["confirmed_count"] or 0), disbursed_count),
                "median_days_to_disbursement": _seconds_to_days(row["median_wait_seconds"]),
                # Per *affected* household, which is the denominator the brief names. Per
                # household disbursed would be the mean payment and would say nothing about
                # coverage - a district that paid one household in full would lead the table.
                "disbursed_per_household_lkr_cents": (
                    disbursed_cents // assessed_households if assessed_households else None
                ),
                "grievance_count": int(row["grievance_count"] or 0),
                "grievance_open_count": int(row["grievance_open_count"] or 0),
                # Per thousand disbursements, so a large district and a small one are
                # comparable. Null where nothing was disbursed: a complaint rate with no
                # denominator is not a rate.
                "grievance_rate_per_1000_disbursements": (
                    round(int(row["grievance_count"] or 0) * 1000 / disbursed_count, 1)
                    if disbursed_count
                    else None
                ),
                "median_grievance_resolution_days": _seconds_to_days(
                    row["median_resolution_seconds"]
                ),
                "last_released_at": _iso(row["last_released_at"]),
            }
        )

    return {"districts": districts, "as_of": _now_iso(), "note": DISTRICT_NOTE}


@router.get("/districts/{district_code}", response_model=DistrictDetail)
async def public_district_detail(
    session: PublicSessionDep,
    district_code: str = Path(examples=["LK-21"]),
    min_cell: int = Query(
        default=MIN_CELL_SIZE,
        ge=MIN_CELL_SIZE,
        description="Raise the privacy floor. It cannot be lowered: the minimum accepted "
        f"value is the policy floor of {MIN_CELL_SIZE}.",
    ),
) -> Any:
    """One district by DS division, with the small cells withheld and counted.

    The suppression is applied here rather than in SQL because the withheld rows still have
    to be totalled: a page that dropped them would show DS columns that do not add up to
    the district figure on the previous screen, and a reader who noticed would be right to
    distrust both.
    """
    if not _DISTRICT_CODE.match(district_code):
        raise ValidationFailed(
            "Not a district code.",
            context={"district_code": district_code, "expected": "LK-NN"},
        )

    rows = await queries.public_district_detail(session, district_code=district_code)
    result = apply_minimum_cell_size(rows, min_cell=min_cell)

    published = [
        {
            "ds_division_code": row["ds_division_code"],
            "assessed_count": int(row["assessed_count"] or 0),
            "assessed_households": int(row["assessed_households"] or 0),
            "assessed_divisions": int(row["assessed_divisions"] or 0),
            "assessed_lkr_cents": int(row["assessed_lkr_cents"] or 0),
            "approved_count": int(row["approved_count"] or 0),
            "approved_lkr_cents": int(row["approved_lkr_cents"] or 0),
            "disbursed_count": int(row["disbursed_count"] or 0),
            "disbursed_lkr_cents": int(row["disbursed_lkr_cents"] or 0),
            "confirmed_count": int(row["confirmed_count"] or 0),
            "median_days_to_disbursement": _seconds_to_days(row["median_wait_seconds"]),
        }
        for row in result.rows
    ]

    return {
        "district_code": district_code,
        "divisions": published,
        "suppressed_divisions": result.divisions,
        "suppressed_disbursements": result.disbursements,
        "suppressed_lkr_cents": result.lkr_cents,
        "minimum_cell_size": min_cell,
        "suppression_note": SUPPRESSION_NOTE,
        "totals": {
            "ds_division_code": district_code,
            **result.totals,
            # Deliberately absent at the district level. A median of medians is not a
            # median, and computing the real one would need every interval again - which
            # /districts already publishes correctly.
            "median_days_to_disbursement": None,
        },
        "as_of": _now_iso(),
    }


def _confirmation_window() -> int:
    """The reply window, read from the one module that defines it.

    Imported inside the function rather than at module scope: `api.v1.ledger` imports this
    module's siblings, and a top-level import here would close the cycle.
    """
    from ledger_svc.api.v1.ledger import CONFIRMATION_WINDOW_DAYS

    return CONFIRMATION_WINDOW_DAYS
