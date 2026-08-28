"""The ledger: authenticated detail, public aggregates, anchors, and cost schedules.

Three of these endpoints take no credential at all, and that is the product rather than a
convenience. A journalist checking whether the money we say was disbursed matches what was
recorded must not need an account issued by the institution whose numbers they are
checking. `tools/sarana-verify` reads exactly these endpoints and nothing else.

The anonymisation lives in the SQL, not here. `queries.public_ledger_entries` selects no
household, no assessment, no GN division and no geometry, so a field added carelessly to a
response model cannot leak an identifier - there is nothing in the row to leak.

`/ledger/public` is per-entry rather than aggregated, which the brief's own requirements
force: it also says `sarana-verify` "recomputes every entry hash" from this feed, and a
total is a claim rather than something anyone can check. The aggregate the dashboard wants
is a second endpoint, `/public/ledger-summary`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.api.deps import PublicSessionDep, SessionDep
from ledger_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope

router = APIRouter(tags=["ledger"])

LedgerReader = Depends(require(Scope.LEDGER_READ))

# How long a household has to answer the confirmation SMS before silence is reported as
# `unconfirmed`. Same seven days as `domain.grievance.CONFIRMATION_WINDOW_DAYS`.
CONFIRMATION_WINDOW_DAYS = 7


class LedgerEntry(BaseModel):
    """One disbursement, in full. Authenticated - this names a household."""

    model_config = ConfigDict(frozen=True)

    seq: int
    id: str
    entitlement_id: str
    amount_lkr_cents: int
    released_by: str
    released_at: datetime
    payment_rail: str
    payment_ref: str | None
    prev_hash: str | None
    entry_hash: str | None
    citizen_confirmed: bool
    citizen_confirmed_at: datetime | None
    gn_division_code: str
    household_id: str
    assessment_ref: str


class PublicLedgerEntry(BaseModel):
    """One disbursement as the world sees it.

    Carries the hashes and every field they cover, and nothing else. No household, no
    division, no assessment reference, no coordinate, no name, no NIC, no phone. The two
    UUIDs have no public resolver, and `released_by` stays because a ledger that does not
    commit to who released public money is not an accountability record.
    """

    model_config = ConfigDict(frozen=True)

    seq: int
    entitlement_id: str
    amount_lkr_cents: int
    released_by: str
    released_at: str = Field(
        description="ISO 8601 UTC, as a string. The hashed bytes and the published bytes "
        "are the same bytes."
    )
    payment_rail: str
    payment_ref: str | None
    prev_hash: str | None
    entry_hash: str | None
    anchor_date: str


class PublicLedgerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    entries: list[PublicLedgerEntry]
    next_seq: int | None = Field(
        default=None, description="Pass as from_seq to continue. Null when the feed ends."
    )
    scheme: dict[str, str]
    note: str = Field(description="How to verify these figures independently.")


class PublicSummaryRow(BaseModel):
    """Disbursements for one district on one day, for the dashboard."""

    model_config = ConfigDict(frozen=True)

    district_code: str
    released_on: date
    cost_schedule_version: str
    disbursement_count: int
    total_lkr_cents: int
    first_seq: int
    last_seq: int
    citizen_confirmed_count: int


class AnchorRow(BaseModel):
    """One day's Merkle root. The thing an outside verifier actually checks.

    The first six fields are exactly the object under compliance-mode lock in S3, field for
    field and name for name, so the published record and the immutable one can be compared
    without translating between them. `prev_anchor_hash` chains the days: removing an
    entire day is then as detectable as altering one row inside it.
    """

    model_config = ConfigDict(frozen=True)

    date: str
    merkle_root: str
    entry_count: int
    first_seq: int
    last_seq: int
    prev_anchor_hash: str | None
    s3_object_lock_uri: str | None
    published_at: datetime | None


class AnchorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    anchors: list[AnchorRow]
    scheme: dict[str, str] = Field(
        description="The published hashing rules, so a verifier needs no source access."
    )


class ScheduleLineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    subcategory: str
    description: dict[str, str]
    unit: str
    rate_lkr_cents: int
    cap_lkr_cents: int | None
    formula: dict[str, Any]


class ScheduleOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    published_at: datetime
    source_ref: str | None
    effective_from: date
    effective_to: date | None
    lines: list[ScheduleLineOut]


# Repeated verbatim in every anchor response so a verifier can reproduce the chain from the
# API alone, without reading this repository. The pair-hash rule concatenates hex digests
# rather than raw bytes on purpose: it costs nothing and lets somebody reproduce a root
# with `sha256sum` and a shell loop.
HASH_SCHEME = {
    "entry_hash": "SHA256( canonical_json(entry_without_hashes) || prev_hash )",
    "entry_without_hashes": "the entry minus prev_hash, entry_hash, seq and anchor_date",
    "canonical_json": "RFC 8785 JSON Canonicalization Scheme",
    "genesis_prev_hash": "64 zero characters",
    "merkle_leaf": "SHA256( canonical_json(entry_without_hashes) )",
    "merkle_pair": "SHA256( left_hex || right_hex )",
    "merkle_odd_node": "the last node is duplicated and paired with itself",
    "verifier": "tools/sarana-verify in the SARANA repository",
}

PUBLIC_NOTE = (
    "Every entry, anonymised. Verify against /api/v1/ledger/anchors and the S3 Object "
    "Lock objects with tools/sarana-verify; it needs no credentials and no access to us. "
    "Recompute each entry_hash over the entry with prev_hash, entry_hash, seq and "
    "anchor_date removed."
)


@router.get("/ledger", response_model=list[LedgerEntry])
async def read_ledger(
    session: SessionDep,
    principal: Principal = LedgerReader,
    from_seq: int = Query(default=0, ge=0),
    to_seq: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> Any:
    """Full ledger detail, by sequence range.

    Row-level security has already restricted this to the caller's areas, so an officer
    paging from seq 0 sees their own districts and a contiguous-looking range with gaps
    where other districts sit. That is correct, and it is why the public feed is a
    separate query rather than this one with the scope removed.
    """
    return await queries.ledger_page(session, from_seq=from_seq, to_seq=to_seq, limit=limit)


@router.get("/ledger/public", response_model=PublicLedgerResponse)
async def public_ledger(
    session: PublicSessionDep,
    from_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> Any:
    """The anonymised per-entry feed. No authentication.

    Per entry rather than aggregated, because an aggregate cannot be verified: a total is
    a claim, and recomputing a hash chain needs the entries the chain is over. The
    aggregate view the dashboard uses is at /api/v1/public/ledger-summary.

    Paged by `seq` and never by date. A verifier walking the chain needs it unbroken, and
    a date filter would produce gaps it could not tell apart from removed entries - which
    is precisely the alarm the chain exists to raise.
    """
    entries = await queries.public_ledger_entries(session, from_seq=from_seq, limit=limit)
    return {
        "entries": entries,
        "next_seq": (entries[-1]["seq"] + 1) if len(entries) == limit else None,
        "scheme": HASH_SCHEME,
        "note": PUBLIC_NOTE,
    }


@router.get("/public/ledger-summary", response_model=list[PublicSummaryRow])
async def public_ledger_summary(
    session: PublicSessionDep,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
) -> Any:
    """Disbursement totals by district and Colombo day, for the dashboard. No auth.

    There is no `min_group_size` parameter. Small-cell suppression is a policy decision
    about re-identification risk, not something a caller should be able to lower by
    editing a URL.
    """
    return await queries.public_ledger(
        session, from_date=from_date, to_date=to_date, min_group_size=1, limit=limit
    )


@router.get("/ledger/anchors", response_model=AnchorResponse)
async def ledger_anchors(
    session: PublicSessionDep,
    limit: int = Query(default=400, ge=1, le=2000),
) -> Any:
    """Every daily Merkle root, newest first. No authentication.

    Carries the hashing scheme with it. An anchor whose verification rules live only in a
    repository README is one repository rewrite away from being uncheckable.
    """
    return {"anchors": await queries.list_anchors(session, limit=limit), "scheme": HASH_SCHEME}


@router.get("/cost-schedules", response_model=list[ScheduleOut])
async def cost_schedules(session: PublicSessionDep) -> Any:
    """Every schedule version, with every line and its published formula. No auth.

    Public because a household told what it is entitled to can read the same formula the
    system used. That is the difference between a figure that is contestable and one that
    is merely announced.
    """
    schedules = await queries.list_cost_schedules(session)
    lines = await queries.cost_schedule_lines(session)

    by_schedule: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        by_schedule.setdefault(line["cost_schedule_id"], []).append(line)

    return [{**schedule, "lines": by_schedule.get(schedule["id"], [])} for schedule in schedules]


@router.get("/public/grievances")
async def public_grievance_stats(session: PublicSessionDep) -> Any:
    """Grievance counts and median resolution time, by district. No authentication.

    Published because a transparency system that hides its own complaint rate is not one.
    A district with zero grievances is not a district doing well - it is usually a
    district where nobody knows the mechanism exists.
    """
    return {
        "districts": await queries.public_grievance_stats(session),
        "note": (
            "A low complaint count is not evidence of a low error rate. Read it alongside "
            "the confirmation rate at /api/v1/public/confirmation-rate."
        ),
    }


@router.get("/public/confirmation-rate")
async def public_confirmation_rate(session: PublicSessionDep) -> Any:
    """How many households confirmed receipt, and how many never answered.

    `unconfirmed` is reported as its own number and never folded into a failure count. No
    reply means a dead phone, an SMS that never arrived, or a message nobody understood -
    none of which is evidence the money is missing.
    """
    counts = await queries.confirmation_rate(session, window_days=CONFIRMATION_WINDOW_DAYS)
    released = int(counts["released"] or 0)
    confirmed = int(counts["confirmed"] or 0)

    return {
        "released": released,
        "confirmed": confirmed,
        "unconfirmed": int(counts["unconfirmed"] or 0),
        "awaiting_reply": int(counts["awaiting"] or 0),
        "confirmation_rate": round(confirmed / released, 4) if released else None,
        "window_days": CONFIRMATION_WINDOW_DAYS,
        "note": (
            "unconfirmed is not failed. A household that did not reply has told us "
            "nothing about whether the money arrived."
        ),
    }
