"""Reading and verifying the audit log.

Writing is not here: entries arrive service-to-service on `/internal/v1/audit`. Keeping
the write path off the public surface means no bearer token, however privileged, can
append a line to the record of who did what.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from core_api.api.deps import SessionDep
from core_api.domain import audit_chain
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

AuditorPrincipal = Depends(require(Scope.AUDIT_READ))

# A verification pass recomputes a sha256 per row. Wide open, it is a denial-of-service
# vector against the auditor's own database; the range is chunked instead.
MAX_VERIFY_RANGE = 50_000


class AuditEntryResponse(BaseModel):
    """One recorded action, with its place in the chain."""

    model_config = ConfigDict(frozen=True)

    id: str
    seq: int
    occurred_at: datetime
    actor_type: str
    actor_id: str | None
    agent_name: str | None
    action: str
    subject_type: str
    subject_id: str
    correlation_id: str
    langgraph_thread_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    prev_hash: str | None
    entry_hash: str | None


class DivergenceResponse(BaseModel):
    """Where and how the chain stopped adding up."""

    model_config = ConfigDict(frozen=True)

    seq: int
    reason: str
    expected: str | None
    found: str | None


class VerifyResponse(BaseModel):
    """The result of recomputing a range of the chain."""

    model_config = ConfigDict(frozen=True)

    intact: bool
    checked: int
    from_seq: int
    to_seq: int
    divergence: DivergenceResponse | None = None


@router.get("", response_model=list[AuditEntryResponse])
async def search_audit(
    session: SessionDep,
    principal: Principal = AuditorPrincipal,
    subject_type: str | None = Query(default=None, max_length=48),
    subject_id: str | None = Query(default=None, max_length=64),
    actor_id: UUID | None = Query(default=None),
    correlation_id: str | None = Query(default=None, max_length=64),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Audit entries matching a filter, newest first."""
    if from_time and to_time and to_time < from_time:
        raise ValidationFailed("`to` is before `from`")

    return await audit_chain.search_entries(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        offset=offset,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify_chain(
    session: SessionDep,
    principal: Principal = AuditorPrincipal,
    from_seq: int | None = Query(default=None, ge=1),
    to_seq: int | None = Query(default=None, ge=1),
) -> Any:
    """Recompute the hash chain over a range and report the first divergence.

    The internal counterpart of the public `sarana-verify` CLI. Both answer the same
    question - has this record been edited since it was written - and both must be able to
    answer it without trusting the application that wrote it.

    Recomputation happens in the database using the same expression as the chain trigger,
    so verification cannot drift from the thing it verifies.
    """
    lowest, highest = await audit_chain.chain_bounds(session)
    if highest == 0:
        return {"intact": True, "checked": 0, "from_seq": 0, "to_seq": 0, "divergence": None}

    start = from_seq if from_seq is not None else lowest
    end = to_seq if to_seq is not None else highest

    if end < start:
        raise ValidationFailed(
            "to_seq is before from_seq", context={"from_seq": start, "to_seq": end}
        )
    if end - start + 1 > MAX_VERIFY_RANGE:
        raise ValidationFailed(
            f"a verification range is capped at {MAX_VERIFY_RANGE:,} entries. "
            "Verify in chunks; each chunk still checks its link to the one before it.",
            context={"requested": end - start + 1, "maximum": MAX_VERIFY_RANGE},
        )

    result = await audit_chain.verify_range(session, from_seq=start, to_seq=end)

    if not result.intact:
        _log.error(
            "audit_chain_divergence",
            seq=result.divergence.seq if result.divergence else None,
            reason=result.divergence.reason if result.divergence else None,
            requested_by=principal.subject_id,
        )

    return result.as_dict()
