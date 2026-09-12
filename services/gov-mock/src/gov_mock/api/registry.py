"""GN officer registry (`/gnreg`) and household registry (`/hhreg`).

Two routers in one module because they are one register in practice — the household roll is
maintained by the officers on the officer roll — and splitting them across files would put
the NIC rules a long way from the households they apply to.

**Read `gov_mock.data.names` before changing anything here.** Every name is generated, the
distribution across districts is deliberate, and the composition weights that drive it are
not demographic data and must never be surfaced as such.

**`verify-nic` never raises for a NIC the register cannot find.** `not_found` is an answer,
not a failure, and it happens to roughly one well-formed NIC in twelve. A household that
cannot be verified is one that needs a manual check, never one that is dropped from an aid
list.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from gov_mock.api.deps import StateDep, mock_json
from gov_mock.data import registry as registry_data
from gov_mock.data.districts import district_for

officers_router = APIRouter(prefix="/gnreg/v1", tags=["gnreg"])
households_router = APIRouter(prefix="/hhreg/v1", tags=["hhreg"])


class NicIn(BaseModel):
    """A NIC to check against the register."""

    model_config = ConfigDict(extra="forbid")

    nic: str = Field(min_length=1, max_length=32)


def _officer_body(officer: registry_data.Officer) -> dict[str, Any]:
    return {
        "service_no": officer.service_no,
        "name": officer.name,
        "gn_division_code": officer.gn_division_code,
        "contact_msisdn": officer.contact_msisdn,
        "appointed_year": officer.appointed_year,
        "active": officer.active,
    }


@officers_router.get("/officers", summary="Officers posted to a GN division")
def officers(state: StateDep, gn_division_id: str = Query(description="GN division code")) -> Any:
    """The officers posted to one division.

    An empty list is a real answer, not a 404: the division exists and has no officer,
    which is the single most useful thing this register can say during an event.
    """
    if district_for(gn_division_id) is None:
        raise HTTPException(status_code=404, detail="No such GN division")

    found = registry_data.officers_for(gn_division_id, seed=state.seed)
    return mock_json({"officers": [_officer_body(officer) for officer in found]})


@officers_router.get("/officers/{service_no}", summary="One officer by service number")
def officer(service_no: str, state: StateDep) -> Any:
    """One officer."""
    found = registry_data.officer_by_service_no(service_no, seed=state.seed)
    if found is None:
        raise HTTPException(status_code=404, detail="No officer with that service number")
    return mock_json({"officer": _officer_body(found)})


def _household_body(household: registry_data.Household) -> dict[str, Any]:
    return {
        "household_ref": household.household_ref,
        "gn_division_code": household.gn_division_code,
        "head_name": household.head_name,
        "head_nic": household.head_nic,
        "address": household.address,
        "member_count": household.member_count,
        "registry_note": household.registry_note,
    }


@households_router.get("/households", summary="Households in a GN division")
def households(
    state: StateDep,
    gn_division_id: str = Query(description="GN division code"),
    cursor: str | None = Query(default=None, description="Opaque cursor from a prior page"),
) -> Any:
    """One page of households.

    Cursor-paginated with an awkward page size, because the real register is. A caller that
    assumes an offset, or a round page size, works until the first division large enough to
    need a second page — which is most of them.
    """
    if district_for(gn_division_id) is None:
        raise HTTPException(status_code=404, detail="No such GN division")

    start = 0
    if cursor is not None:
        if not cursor.isdigit():
            raise HTTPException(status_code=422, detail="Malformed cursor")
        start = int(cursor)

    everyone = registry_data.households_for(gn_division_id, seed=state.seed)
    page = everyone[start : start + registry_data.PAGE_SIZE]
    next_start = start + registry_data.PAGE_SIZE

    return mock_json(
        {
            "page": {
                "households": [_household_body(household) for household in page],
                "next_cursor": str(next_start) if next_start < len(everyone) else None,
            }
        }
    )


@households_router.get("/households/{household_ref}", summary="One household by reference")
def household(household_ref: str, state: StateDep) -> Any:
    """One household."""
    found = registry_data.household_by_ref(household_ref, seed=state.seed)
    if found is None:
        raise HTTPException(status_code=404, detail="No household with that reference")
    return mock_json({"household": _household_body(found)})


@households_router.post("/verify-nic", summary="Verify a National Identity Card number")
def verify_nic(payload: NicIn) -> Any:
    """Check a NIC against the register.

    Three outcomes, and all three are 200. `not_found` is not an error — it is the register
    saying it has no record, which is a fact about the register and not about the person.
    Returning 404 for it would let a caller treat a registry gap as a bad request and
    reject the household.

    A verified NIC resolves to a division, never to a name. An endpoint that returns a
    person's details for any number presented to it is a bulk lookup facility with a
    verification label on it.
    """
    nic = payload.nic.strip()

    if not registry_data.nic_is_well_formed(nic):
        return mock_json({"verification": {"nic": nic, "outcome": "invalid"}})

    if not registry_data.nic_is_on_register(nic):
        return mock_json({"verification": {"nic": nic, "outcome": "not_found"}})

    return mock_json(
        {
            "verification": {
                "nic": nic,
                "outcome": "valid",
                "gn_division_code": registry_data.division_for_nic(nic),
            }
        }
    )
