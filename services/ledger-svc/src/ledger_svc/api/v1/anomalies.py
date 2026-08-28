"""Anomaly flags: the system questioning a pattern in the data.

ADR-009, and every line of it matters. A flag is **advisory**, **never public**, and
**never names a person** - the database enforces the last of those with a CHECK that
rejects any rationale containing an officer, assessor or user id at any nesting depth.

Divisions with genuinely worse damage will legitimately look like outliers. That is the
damage behaving as expected, not evidence about whoever assessed it, and a system that
confuses the two does more harm than the fraud it catches. So:

  - every flag needs a human disposition before it can close;
  - FALSE_POSITIVE is a first-class outcome, not a failure to be hidden, because the
    false-positive rate is reported alongside the detection rate;
  - a disposition requires a note. "Reviewed" with no reasoning is not a review.

There is no public route to this data anywhere in the service. It is not on the
transparency dashboard, and it is not in the public ledger feed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ledger_svc.adapters.events import publish
from ledger_svc.api.deps import SessionDep
from ledger_svc.repo import ANOMALY_DISPOSITIONS, ANOMALY_SUBJECTS, queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Conflict, NotFound, ValidationFailed
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["anomalies"])

ReadPrincipal = Depends(require(Scope.ANOMALY_READ))
DisposePrincipal = Depends(require(Scope.ANOMALY_DISPOSE))


class AnomalyOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    subject_type: str
    subject_id: str
    detector: str
    detector_version: str
    score: float
    rationale: dict[str, Any]
    raised_at: datetime
    disposition: str
    disposed_by: str | None = None
    disposed_at: datetime | None = None
    disposition_note: str | None = None


class DisposeRequest(BaseModel):
    """Closing a flag.

    The note is required for every outcome including FALSE_POSITIVE. A flag closed without
    reasoning tells the next reviewer nothing, and the false-positive rate is only
    meaningful if somebody can read why each one was called.
    """

    model_config = ConfigDict(extra="forbid")

    disposition: str = Field(
        description=f"One of: {', '.join(d for d in ANOMALY_DISPOSITIONS if d != 'OPEN')}"
    )
    note: str = Field(min_length=1, max_length=2000)


@router.get("/anomalies", response_model=list[AnomalyOut])
async def list_anomalies(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    disposition: str | None = Query(default=None),
    subject_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Flags in the caller's scope. AUDITOR and district roles only, never public."""
    if subject_type is not None and subject_type not in ANOMALY_SUBJECTS:
        raise ValidationFailed(
            f"{subject_type!r} is not an anomaly subject; expected one of "
            f"{', '.join(ANOMALY_SUBJECTS)}"
        )
    return await queries.list_anomalies(
        session,
        disposition=disposition,
        subject_type=subject_type,
        limit=limit,
        offset=offset,
    )


@router.get("/anomalies/{anomaly_id}", response_model=AnomalyOut)
async def read_anomaly(
    anomaly_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    found = await queries.get_anomaly(session, anomaly_id)
    if found is None:
        raise NotFound("No such anomaly flag.")
    return found


@router.post("/anomalies/{anomaly_id}/dispose", response_model=AnomalyOut)
async def dispose_anomaly(
    anomaly_id: UUID,
    body: DisposeRequest,
    session: SessionDep,
    principal: Principal = DisposePrincipal,
) -> Any:
    """Close a flag with a human decision and a reason.

    A flag can be disposed once. Reopening it would let a disposition be replaced quietly,
    and the point of recording who closed a flag and why is that the record survives
    disagreement about it.
    """
    if body.disposition not in ANOMALY_DISPOSITIONS or body.disposition == "OPEN":
        raise ValidationFailed(
            f"{body.disposition!r} does not close a flag; expected one of "
            f"{', '.join(d for d in ANOMALY_DISPOSITIONS if d != 'OPEN')}"
        )

    found = await queries.get_anomaly(session, anomaly_id)
    if found is None:
        raise NotFound("No such anomaly flag.")

    updated = await queries.dispose_anomaly(
        session,
        anomaly_id=anomaly_id,
        disposition=body.disposition,
        disposed_by=UUID(principal.subject_id),
        note=body.note,
    )
    if updated is None:
        raise Conflict(
            f"this flag was already dispositioned as {found['disposition']}. A new "
            "concern about the same subject is a new flag."
        )

    publish(
        session,
        catalogue.AID_ANOMALY_DISPOSED,
        {
            "anomaly_id": updated["id"],
            "subject_type": updated["subject_type"],
            "disposition": updated["disposition"],
            # Tracked as a first-class metric and reported alongside the detection rate.
            "false_positive": updated["disposition"] == "FALSE_POSITIVE",
        },
        subject=updated["id"],
    )
    _log.info(
        "anomaly_disposed",
        anomaly_id=updated["id"],
        disposition=updated["disposition"],
    )
    return {**found, **updated, "disposed_by": principal.subject_id, "disposition_note": body.note}
