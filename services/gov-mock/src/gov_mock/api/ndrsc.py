"""NDRSC routes: the cost schedules, and the claims register.

Read `sarana_shared.adapters.gov.ndrsc` first. The direction of this integration is
load-bearing: the CMS is the system of record and SARANA pushes into it. There is
deliberately no route that edits or withdraws a submitted claim.

`POST /claims` is idempotent on `client_reference`. Re-submitting returns the existing
receipt rather than creating a second claim — which is what makes a retry after a timeout
safe, and a timeout on a claims call is exactly when a retry is most tempting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import SimulatedNowDep, StateDep, mock_json
from gov_mock.data import ndrsc as ndrsc_data
from gov_mock.state import Claim, MockState

router = APIRouter(prefix="/ndrsc/v1", tags=["ndrsc"])


class ClaimIn(BaseModel):
    """A completed, approved claim being pushed into the CMS."""

    model_config = ConfigDict(extra="forbid")

    client_reference: str = Field(min_length=1, max_length=64)
    household_reference: str = Field(min_length=1, max_length=64)
    gn_division_code: str = Field(min_length=1, max_length=16)
    cost_schedule_version: str = Field(min_length=1, max_length=16)
    amount_lkr_cents: int = Field(ge=0)
    assessed_at: datetime
    approved_by: list[str] = Field(default_factory=list)
    calculation_trace: dict[str, Any] = Field(default_factory=dict)


def _schedule_body(schedule: ndrsc_data.Schedule) -> dict[str, Any]:
    return {
        "version": schedule.version,
        "published_at": schedule.published_at.isoformat(),
        "effective_from": schedule.effective_from.isoformat(),
        "household_cap_cents": schedule.household_cap_cents,
        "lines": [
            {
                "line_id": line.line_id,
                "category": line.category,
                "unit_amount_cents": line.unit_amount_cents,
                "max_units": line.max_units,
                "formula": line.formula,
            }
            for line in schedule.lines
        ],
    }


@router.get("/cost-schedules", summary="Every published cost schedule")
def cost_schedules() -> Any:
    """All versions, newest first."""
    return mock_json(
        {"cost_schedules": [_schedule_body(schedule) for schedule in ndrsc_data.SCHEDULES]}
    )


@router.get("/cost-schedules/{version}", summary="One cost schedule version")
def cost_schedule(version: str) -> Any:
    """One version.

    404 for a version that was never published. Never a fallback to the current one: an
    entitlement pinned to a version that no longer exists is an audit finding, and quietly
    valuing it against today's rates would hide it.
    """
    schedule = ndrsc_data.BY_VERSION.get(version)
    if schedule is None:
        raise HTTPException(status_code=404, detail="No such cost schedule version")
    return mock_json({"cost_schedule": _schedule_body(schedule)})


def _claim_body(claim: Claim, state: MockState, now: datetime) -> dict[str, Any]:
    """Render a claim, computing its status from how long the CMS has had it."""
    age_hours = (now - claim.received_at).total_seconds() / 3600.0
    returned = ndrsc_data.is_returned(claim.client_reference)

    if age_hours < ndrsc_data.REVIEW_AFTER_HOURS:
        status = "RECEIVED"
        reason = None
    elif age_hours < ndrsc_data.DECISION_AFTER_HOURS:
        status = "UNDER_REVIEW"
        reason = None
    elif returned:
        status = "RETURNED"
        reason = ndrsc_data.return_reason(claim.client_reference)
    elif age_hours < ndrsc_data.PAID_AFTER_HOURS:
        status = "APPROVED"
        reason = None
    else:
        status = "PAID"
        reason = None

    return {
        "claim_reference": claim.claim_reference,
        "client_reference": claim.client_reference,
        "status": status,
        "received_at": claim.received_at.isoformat(),
        # The instant this status was reached, not "now". A caller polling every minute
        # should see `updated_at` move only when something actually changed.
        "updated_at": max(claim.received_at, claim.updated_at).isoformat(),
        "reason": reason,
    }


@router.post("/claims", summary="Push a completed claim into the CMS", status_code=201)
def submit_claim(payload: ClaimIn, state: StateDep, now: SimulatedNowDep) -> Any:
    """Submit a claim. Idempotent on `client_reference`."""
    if payload.cost_schedule_version not in ndrsc_data.BY_VERSION:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Claim cites cost schedule {payload.cost_schedule_version!r}, which the "
                "CMS has never published. A claim the CMS cannot price is one it cannot pay."
            ),
        )
    if not payload.approved_by:
        # The CMS's own rule, and worth mirroring: a claim with no named approver is not a
        # claim, it is a number somebody typed.
        raise HTTPException(status_code=422, detail="A claim must name at least one approver")

    existing_ref = state.claims_by_client_ref.get(payload.client_reference)
    if existing_ref is not None:
        return mock_json({"claim": _claim_body(state.claims[existing_ref], state, now)})

    sequence = state.next_sequence()
    claim = Claim(
        claim_reference=f"NDRSC-CLAIM-{now:%Y%m}-{sequence:06d}",
        client_reference=payload.client_reference,
        household_reference=payload.household_reference,
        amount_lkr_cents=payload.amount_lkr_cents,
        received_at=now,
        updated_at=now,
        payload=payload.model_dump(mode="json"),
    )
    state.claims[claim.claim_reference] = claim
    state.claims_by_client_ref[payload.client_reference] = claim.claim_reference

    return mock_json({"claim": _claim_body(claim, state, now)}, status_code=201)


@router.get("/claims/{claim_reference}", summary="Claim status")
def claim_status(claim_reference: str, state: StateDep, now: SimulatedNowDep) -> Any:
    """Read a claim's current status back from the CMS."""
    claim = state.claims.get(claim_reference)
    if claim is None:
        raise HTTPException(status_code=404, detail="No such claim")
    return mock_json({"claim": _claim_body(claim, state, now)})
