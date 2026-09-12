"""Alert templates and their review workflow.

The review endpoints are the trilingual gate made operational: a named Sinhala reviewer
and a named Tamil reviewer each sign, and only then can a template be published.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from alerting_svc.api.deps import SessionDep
from alerting_svc.domain import templates as template_rules
from alerting_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import Conflict, NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["templates"])

ReadPrincipal = Depends(require(Scope.ALERT_READ))
DraftPrincipal = Depends(require(Scope.ALERT_DRAFT))
ApprovePrincipal = Depends(require(Scope.ALERT_APPROVE))


class TemplateRequest(BaseModel):
    """A new template. Always starts as DRAFT."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=48)
    hazard_type: str = Field(max_length=16)
    severity: str = Field(max_length=12)
    urgency: str = Field(max_length=12)
    certainty: str = Field(max_length=12)
    body: dict[str, str]


class ReviewRequest(BaseModel):
    """One reviewer signing one language.

    The language is explicit rather than inferred from the reviewer: someone who reads
    both should still have to say which one they are signing for.
    """

    model_config = ConfigDict(extra="forbid")

    language: str = Field(pattern="^(si|ta)$")


class TemplateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    status: str


@router.get("/templates")
async def list_templates(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    hazard: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await queries.list_templates(
        session, status=status_filter, hazard=hazard, limit=limit, offset=offset
    )


@router.post("/templates", response_model=TemplateResponse)
async def create_template(
    body: TemplateRequest,
    session: SessionDep,
    principal: Principal = DraftPrincipal,
) -> Any:
    """Create a draft template.

    Validated here rather than at publish time so an author finds out about a missing
    Tamil body while they are still writing it, not weeks later at a release gate.
    """
    try:
        template_rules.validate_template(body.body)
    except template_rules.TemplateInvalid as error:
        raise ValidationFailed(str(error), context={"code": body.code}) from error

    return await queries.insert_template(
        session,
        code=body.code,
        hazard_type=body.hazard_type,
        severity=body.severity,
        urgency=body.urgency,
        certainty=body.certainty,
        body=json.dumps(body.body),
    )


@router.post("/templates/{template_id}/review")
async def review_template(
    template_id: UUID,
    body: ReviewRequest,
    session: SessionDep,
    principal: Principal = ApprovePrincipal,
) -> Any:
    """Record one native reviewer's signature.

    The reviewer's identity comes from their token, never from the request body. A review
    somebody else can attribute to you is not a review.
    """
    template = await queries.get_template(session, template_id)
    if template is None:
        raise NotFound("No such template.", context={"template_id": str(template_id)})

    reviewer = UUID(principal.subject_id)
    updated = await queries.record_review(
        session,
        template_id,
        reviewer_si=reviewer if body.language == "si" else None,
        reviewer_ta=reviewer if body.language == "ta" else None,
    )
    if updated is None:
        raise Conflict(
            "that template is already published or retired and cannot be reviewed",
            context={"template_id": str(template_id)},
        )

    _log.info(
        "template_reviewed",
        template_id=str(template_id),
        language=body.language,
        reviewer=principal.subject_id,
        status=updated["status"],
    )
    return updated


@router.post("/templates/{template_id}/publish", response_model=TemplateResponse)
async def publish_template(
    template_id: UUID,
    session: SessionDep,
    principal: Principal = ApprovePrincipal,
) -> Any:
    """Publish a fully reviewed template.

    Refused unless both signatures are present. The database predicate does the refusing
    as well, so a code path that forgets to check cannot bypass it.
    """
    template = await queries.get_template(session, template_id)
    if template is None:
        raise NotFound("No such template.", context={"template_id": str(template_id)})

    review = template_rules.TemplateReview(
        reviewed_by_si=UUID(template["reviewed_by_si"]) if template["reviewed_by_si"] else None,
        reviewed_by_ta=UUID(template["reviewed_by_ta"]) if template["reviewed_by_ta"] else None,
    )
    try:
        template_rules.assert_publishable(template["body"], review)
    except template_rules.ReviewIncomplete as error:
        raise Conflict(str(error), context={"missing": list(review.missing)}) from error
    except template_rules.TemplateInvalid as error:
        raise ValidationFailed(str(error)) from error

    published = await queries.publish_template(session, template_id)
    if published is None:
        raise Conflict(
            "the database refused to publish this template; its review is incomplete",
            context={"template_id": str(template_id)},
        )

    _log.info("template_published", template_id=str(template_id), code=published["code"])
    return published
