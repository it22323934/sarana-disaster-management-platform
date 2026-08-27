"""Telco and mesh webhooks.

Mounted under `/internal/v1`. These are called by the mock telco and mesh gateways, never
by a browser, and they carry no citizen credential - the sender is identified by an HMAC
of their number, which the platform can match without ever decrypting it.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from incident_svc.adapters.channels import lora, paper, sms, ussd
from incident_svc.api.deps import CorrelationDep, SessionDep
from incident_svc.service import intake as intake_service
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal/v1/channels", tags=["channels"])

# Machine-to-machine only. The gateway holds a service principal; a citizen never calls
# these directly.
GatewayPrincipal = Depends(require(Scope.INCIDENT_WRITE))


class SmsInbound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_hash: str = Field(min_length=8, max_length=128)
    body: str = Field(max_length=1600)
    received_at: str | None = None


class UssdSession(BaseModel):
    """One keypress in a USSD session.

    The gateway holds the session state and returns it with each turn. Keeping it out of
    this service means a dropped session costs nothing to clean up.
    """

    model_config = ConfigDict(extra="forbid")

    sender_hash: str = Field(min_length=8, max_length=128)
    session_id: str = Field(max_length=64)
    choice: str = Field(default="", max_length=8)
    step: str | None = None
    language: str = Field(default="en", max_length=2)
    incident_type: str | None = None
    people_at_risk: int | None = None


class UssdReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    finished: bool
    step: str
    language: str
    incident_type: str | None = None
    people_at_risk: int | None = None
    report_id: str | None = None


class LoraBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(max_length=64)
    entries: list[dict[str, Any]]


class LoraResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: int
    rejected: list[str]
    report_ids: list[str]


class PaperForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qr_payload: str = Field(max_length=128)
    text: str = Field(max_length=4000)
    incident_type: str | None = None
    people_at_risk: int | None = None
    language: str | None = Field(default=None, max_length=2)


@router.post("/sms/inbound", status_code=status.HTTP_202_ACCEPTED)
async def sms_inbound(
    body: SmsInbound,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """One inbound SMS.

    Never rejects on content. An unparseable message becomes a report with its text intact
    and no type, because the messages that do not match the documented syntax are the ones
    most likely to be genuine emergencies.
    """
    intake = sms.parse(
        body=body.body,
        sender_msisdn_hash=body.sender_hash,
        correlation_id=correlation_id or body.sender_hash,
    )
    result = await intake_service.accept(session, intake, core_api=request.app.state.core_api)
    return {
        "report_id": result.report_id,
        "incident_id": result.incident_id,
        "placed": result.placed,
        "detected_type": intake.incident_type,
        "detected_language": intake.reported_language,
    }


@router.post("/ussd/session", response_model=UssdReply)
async def ussd_session(
    body: UssdSession,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """One turn of the USSD menu."""
    if body.step is None:
        turn = ussd.start()
        return {
            "text": turn.text,
            "finished": turn.finished,
            "step": turn.state.step.value,
            "language": turn.state.language,
        }

    try:
        current = ussd.SessionState(
            step=ussd.Step(body.step),
            language=body.language,
            incident_type=body.incident_type,
            people_at_risk=body.people_at_risk,
        )
    except ValueError as error:
        raise ValidationFailed(f"unknown USSD step {body.step!r}") from error

    try:
        turn = ussd.advance(
            current,
            body.choice,
            sender_msisdn_hash=body.sender_hash,
            correlation_id=correlation_id or body.session_id,
        )
    except ussd.SessionExpired as error:
        raise ValidationFailed(str(error)) from error

    report_id: str | None = None
    if turn.intake is not None:
        result = await intake_service.accept(
            session, turn.intake, core_api=request.app.state.core_api
        )
        report_id = result.report_id

    return {
        "text": turn.text,
        "finished": turn.finished,
        "step": turn.state.step.value,
        "language": turn.state.language,
        "incident_type": turn.state.incident_type,
        "people_at_risk": turn.state.people_at_risk,
        "report_id": report_id,
    }


@router.post("/lora/batch", response_model=LoraResult, status_code=status.HTTP_202_ACCEPTED)
async def lora_batch(
    body: LoraBatch,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """A mesh node's buffered reports.

    Malformed entries are counted and named, not fatal. This batch may be the only copy of
    those reports in existence, and losing forty because one was corrupt would be the
    worst possible outcome.
    """
    try:
        parsed, rejected = lora.parse_batch(
            body.entries, correlation_id=correlation_id or body.node_id
        )
    except ValueError as error:
        raise ValidationFailed(str(error)) from error

    report_ids: list[str] = []
    for intake in parsed:
        result = await intake_service.accept(session, intake, core_api=request.app.state.core_api)
        report_ids.append(result.report_id)

    _log.info(
        "lora_batch_accepted",
        node_id=body.node_id,
        accepted=len(report_ids),
        rejected=len(rejected),
    )
    return {"accepted": len(report_ids), "rejected": rejected, "report_ids": report_ids}


@router.post("/paper/scan", status_code=status.HTTP_202_ACCEPTED)
async def paper_scan(
    body: PaperForm,
    request: Request,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """A GN officer's scanned paper form."""
    try:
        intake = paper.parse(
            qr_payload=body.qr_payload,
            text=body.text,
            correlation_id=correlation_id or body.qr_payload,
            incident_type=body.incident_type,
            people_at_risk=body.people_at_risk,
            language=body.language,
            officer_id=principal.subject_id,
        )
    except paper.UnreadableForm as error:
        raise ValidationFailed(str(error)) from error

    result = await intake_service.accept(session, intake, core_api=request.app.state.core_api)
    return {
        "report_id": result.report_id,
        "incident_id": result.incident_id,
        "placed": result.placed,
    }
