"""The human review queue.

Low-confidence transcription and translation land here and never auto-publish. A machine
that is unsure what a frightened person said in Tamil must hand that to someone who can
read it, not guess and route the result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from incident_svc.api.deps import SessionDep
from incident_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Conflict

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["review"])

ReviewPrincipal = Depends(require(Scope.INCIDENT_VERIFY))


class ReviewItem(BaseModel):
    """One transcription awaiting a human."""

    model_config = ConfigDict(frozen=True)

    id: str
    raw_report_id: str
    channel: str
    provider: str
    model: str
    detected_language: str | None
    text_original: str | None
    text_en: str | None
    confidence: float
    received_at: datetime


class ResolveRequest(BaseModel):
    """A reviewer's correction."""

    model_config = ConfigDict(extra="forbid")

    corrected_text: str = Field(min_length=1, max_length=4000)


@router.get("/review-queue", response_model=list[ReviewItem])
async def review_queue(
    session: SessionDep,
    principal: Principal = ReviewPrincipal,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """Oldest first.

    Deliberately not ranked by confidence. The item waiting longest is the one whose
    reporter has been waiting longest, and confidence says nothing about urgency.
    """
    return await queries.review_queue(session, limit=limit, offset=offset)


@router.post("/review-queue/{transcription_id}/resolve")
async def resolve_review(
    transcription_id: UUID,
    body: ResolveRequest,
    session: SessionDep,
    principal: Principal = ReviewPrincipal,
) -> Any:
    """Record a human's correction and release the report onward."""
    resolved = await queries.resolve_review(
        session,
        transcription_id,
        reviewer_id=UUID(principal.subject_id),
        corrected=body.corrected_text,
    )
    if resolved is None:
        raise Conflict(
            "that transcription has already been reviewed, or does not exist",
            context={"transcription_id": str(transcription_id)},
        )

    _log.info(
        "transcription_reviewed",
        transcription_id=str(transcription_id),
        reviewer=principal.subject_id,
    )
    return resolved
