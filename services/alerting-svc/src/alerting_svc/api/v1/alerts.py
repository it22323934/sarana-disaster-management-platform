"""Alerts: draft, sign off, dispatch, cancel, and prove delivery.

`/delivery/gaps` is the operationally important endpoint. It answers the question this
service exists to answer during an event: which communities probably did not get the
warning, while there is still time to send a vehicle.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from alerting_svc.adapters.channels.base import Target
from alerting_svc.adapters.households import HouseholdDirectory
from alerting_svc.api.deps import CorrelationDep, SessionDep
from alerting_svc.domain import cap, delivery, templates
from alerting_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import Conflict, NotFound, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["alerts"])

ReadPrincipal = Depends(require(Scope.ALERT_READ))
DraftPrincipal = Depends(require(Scope.ALERT_DRAFT))
ApprovePrincipal = Depends(require(Scope.ALERT_APPROVE))
DispatchPrincipal = Depends(require(Scope.ALERT_DISPATCH))


class AlertRequest(BaseModel):
    """A drafted alert: a template, its parameters, and an area."""

    model_config = ConfigDict(extra="forbid")

    template_code: str = Field(max_length=48)
    hazard_event_id: UUID
    parameters: dict[str, str] = Field(default_factory=dict)
    gn_division_ids: list[UUID] = Field(min_length=1)
    gn_division_codes: list[str] = Field(default_factory=list)
    effective_at: datetime
    expires_at: datetime

    # Anything here forces the soft third gate. Accepted rather than refused, because an
    # operator must be able to say something the templates do not cover - but never
    # without a human seeing it first.
    free_text: dict[str, str] | None = Field(
        default=None, description="Free text outside the template. Forces PENDING_SIGNOFF."
    )


class AlertResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    cap_identifier: str
    status: str
    requires_human_signoff: bool


class DispatchRequest(BaseModel):
    """Send it, or say what it would do."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(
        default=False, description="Return counts and cost without sending anything."
    )
    override_cap: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class DeliveryResponse(BaseModel):
    """Counts, always with their denominator."""

    model_config = ConfigDict(frozen=True)

    targeted: int
    confirmed: int
    unconfirmed: int
    failed: int
    no_channel: int
    by_channel: dict[str, dict[str, int]]
    by_language: dict[str, int]
    summary: str = Field(description="What the console shows. Never a bare percentage.")


class GapResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    gn_division_code: str
    targeted: int
    confirmed: int
    confirmed_fraction: float
    summary: str


@router.post("/alerts", response_model=AlertResponse)
async def draft_alert(
    body: AlertRequest,
    session: SessionDep,
    correlation_id: CorrelationDep,
    principal: Principal = DraftPrincipal,
) -> Any:
    """Draft an alert from a published template.

    The soft third gate decides the outcome: template-only alerts land as DRAFT and may be
    dispatched; anything carrying free text lands as PENDING_SIGNOFF and waits for a
    named human.
    """
    template = await queries.get_published_template(session, body.template_code)
    if template is None:
        raise NotFound(
            "No published template with that code.",
            context={"template_code": body.template_code},
        )

    try:
        rendered = templates.render(template["body"], body.parameters, free_text=body.free_text)
    except templates.TemplateInvalid as error:
        raise ValidationFailed(str(error), context={"template_code": body.template_code}) from error

    identifier = f"sarana.lk.{uuid7()}"
    requires_signoff = rendered.requires_signoff

    row = await queries.insert_alert(
        session,
        hazard_event_id=body.hazard_event_id,
        template_id=template["id"],
        cap_identifier=identifier,
        cap_xml=None,
        headline=json.dumps(rendered.body),
        description=json.dumps(rendered.body),
        instruction=json.dumps(rendered.body),
        severity=template["severity"],
        urgency=template["urgency"],
        certainty=template["certainty"],
        effective_at=body.effective_at,
        expires_at=body.expires_at,
        area_gn_division_ids=[str(value) for value in body.gn_division_ids],
        requires_human_signoff=requires_signoff,
        status="PENDING_SIGNOFF" if requires_signoff else "DRAFT",
        correlation_id=correlation_id or identifier,
    )

    _log.info(
        "alert_drafted",
        alert_id=row["id"],
        template=body.template_code,
        requires_signoff=requires_signoff,
        divisions=len(body.gn_division_ids),
    )
    return row


@router.post("/alerts/{alert_id}/signoff", response_model=AlertResponse)
async def sign_off(
    alert_id: UUID,
    session: SessionDep,
    principal: Principal = ApprovePrincipal,
) -> Any:
    """Approve an alert that carries free text.

    Only alerts in PENDING_SIGNOFF can be signed off, and only once. A second caller is
    refused rather than silently succeeding: they may be a different person who needs to
    know the decision was already made.
    """
    signed = await queries.sign_off_alert(session, alert_id, UUID(principal.subject_id))
    if signed is None:
        raise Conflict(
            "that alert is not awaiting sign-off, or has already been signed off",
            context={"alert_id": str(alert_id)},
        )

    _log.info("alert_signed_off", alert_id=str(alert_id), approver=principal.subject_id)
    row = await queries.get_alert(session, alert_id)
    return row


@router.post("/alerts/{alert_id}/dispatch")
async def dispatch_alert(
    alert_id: UUID,
    body: DispatchRequest,
    request: Request,
    session: SessionDep,
    principal: Principal = DispatchPrincipal,
) -> Any:
    """Validate, then fan out over every channel.

    The CAP document is built and validated **before** anything is sent. A schema-invalid
    alert is never dispatched: a consumer that cannot parse it is a broadcaster that does
    not broadcast it.
    """
    alert = await queries.get_alert(session, alert_id)
    if alert is None:
        raise NotFound("No such alert.", context={"alert_id": str(alert_id)})

    if alert["status"] in {"DISPATCHING", "DISPATCHED", "CANCELLED"}:
        raise Conflict(f"alert is already {alert['status']}", context={"alert_id": str(alert_id)})
    if alert["requires_human_signoff"] and not alert["signed_off_by"]:
        raise Conflict(
            "this alert contains free text and has not been signed off. Templates "
            "dispatch immediately; anything else waits for a human.",
            context={"alert_id": str(alert_id)},
        )

    document = cap.CapAlert(
        identifier=alert["cap_identifier"],
        sender=request.app.state.settings.cap_sender,
        sent=alert["created_at"],
        msg_type="Alert",
        status="Actual",
        scope="Public",
        event=alert["headline"].get("en", "Alert"),
        category="Met",
        severity=cap.cap_case(alert["severity"]),
        urgency=cap.cap_case(alert["urgency"]),
        certainty=cap.cap_case(alert["certainty"]),
        headline=alert["headline"],
        description=alert["description"],
        instruction=alert["instruction"],
        effective=alert["effective_at"],
        expires=alert["expires_at"],
        area=cap.Area(gn_codes=[str(value) for value in alert["area_gn_division_ids"]]),
    )

    try:
        cap.validate(document)
    except cap.CapInvalid as error:
        raise ValidationFailed(
            f"the alert does not satisfy CAP 1.2 and was not dispatched: {error}",
            context={"problems": error.problems},
        ) from error

    channels = request.app.state.channels
    targets = await _targets_for(alert, request.app.state.household_directory)

    if body.dry_run:
        # Cannot send: `dry_run` takes no transport at all.
        plan = delivery.dry_run(channels, targets, cap=request.app.state.settings.alert_target_cap)
        return {"dry_run": True, **plan.as_dict()}

    cap_limit = request.app.state.settings.alert_target_cap
    if len(targets) > cap_limit and not body.override_cap:
        raise Conflict(
            f"this alert targets {len(targets):,} people, above the {cap_limit:,} cap. "
            "Confirm the area selection, then retry with override_cap and a reason.",
            context={"targeted": len(targets), "cap": cap_limit},
        )
    if body.override_cap and not (body.override_reason or "").strip():
        raise ValidationFailed("overriding the target cap requires a reason")

    await queries.set_alert_status(session, alert_id, "DISPATCHING", cap_xml=cap.to_xml(document))

    results = await delivery.fan_out(channels, targets, alert["headline"])

    for result in results:
        dispatch = await queries.insert_dispatch(
            session,
            alert_id=alert_id,
            channel=result.channel,
            target_count=len(result.receipts),
            status="FAILED" if result.failed_outright else "SENT",
        )
        for receipt in result.receipts:
            await queries.insert_receipt(
                session,
                dispatch_id=UUID(dispatch["id"]),
                channel=receipt.channel,
                target_ref_hash=receipt.target_ref_hash,
                language=receipt.language or "en",
                status=receipt.status.value,
                provider_ref=receipt.provider_ref,
                failure_reason=receipt.failure_reason,
            )

    await queries.set_alert_status(session, alert_id, "DISPATCHED")
    summary = delivery.summarise(results, targets)

    _log.info(
        "alert_dispatched",
        alert_id=str(alert_id),
        targeted=summary.targeted,
        confirmed=summary.confirmed,
        channels_failed=summary.channels_failed,
    )
    return {"dry_run": False, "alert_id": str(alert_id), "summary": summary.as_sentence()}


@router.post("/alerts/{alert_id}/cancel")
async def cancel_alert(
    alert_id: UUID,
    session: SessionDep,
    principal: Principal = DispatchPrincipal,
) -> Any:
    """Cancel an alert, emitting a CAP Cancel that references the original."""
    alert = await queries.get_alert(session, alert_id)
    if alert is None:
        raise NotFound("No such alert.", context={"alert_id": str(alert_id)})

    await queries.set_alert_status(session, alert_id, "CANCELLED")
    _log.info("alert_cancelled", alert_id=str(alert_id), by=principal.subject_id)
    return {"alert_id": str(alert_id), "status": "CANCELLED"}


@router.get("/alerts")
async def list_alerts(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    return await queries.list_alerts(session, status=status_filter, limit=limit, offset=offset)


@router.get("/alerts/{alert_id}/delivery", response_model=DeliveryResponse)
async def alert_delivery(
    alert_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """Per-channel and per-language counts, with their denominator."""
    alert = await queries.get_alert(session, alert_id)
    if alert is None:
        raise NotFound("No such alert.", context={"alert_id": str(alert_id)})

    rows = await queries.delivery_rows(session, alert_id)
    summary = _summarise_rows(rows)
    return {**summary, "summary": _sentence(summary)}


@router.get("/alerts/{alert_id}/delivery/gaps", response_model=list[GapResponse])
async def alert_gaps(
    alert_id: UUID,
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    threshold: float = Query(default=delivery.GAP_THRESHOLD, ge=0.0, le=1.0),
) -> Any:
    """Divisions that probably did not get the warning, worst first.

    The endpoint an operator acts on: it names where to send a vehicle with a loudhailer,
    in time for that to matter.
    """
    alert = await queries.get_alert(session, alert_id)
    if alert is None:
        raise NotFound("No such alert.", context={"alert_id": str(alert_id)})

    rows = await queries.delivery_rows(session, alert_id)
    per_division: dict[str, dict[str, int]] = {}
    for row in rows:
        # The division is carried in the target hash prefix by the target builder.
        code = row["target_ref_hash"].split(":", 1)[0]
        bucket = per_division.setdefault(code, {"targeted": 0, "confirmed": 0})
        bucket["targeted"] += 1
        if row["status"] in {"SENT", "DELIVERED", "READ"}:
            bucket["confirmed"] += 1

    # Built as the domain's own type rather than an inline dict, so the fraction and the
    # sentence come from one place and cannot drift from what the unit tests assert.
    found = [
        delivery.DivisionGap(
            gn_division_code=code,
            targeted=counts["targeted"],
            confirmed=counts["confirmed"],
        )
        for code, counts in per_division.items()
    ]
    below = sorted(
        (gap for gap in found if gap.confirmed_fraction < threshold),
        key=lambda gap: gap.confirmed_fraction,
    )
    return [
        {
            "gn_division_code": gap.gn_division_code,
            "targeted": gap.targeted,
            "confirmed": gap.confirmed,
            "confirmed_fraction": gap.confirmed_fraction,
            "summary": gap.as_sentence(),
        }
        for gap in below
    ]


@router.get("/alerts/{alert_id}/cap.xml", response_class=Response)
async def alert_cap_xml(alert_id: UUID, session: SessionDep) -> Response:
    """The CAP document, publicly.

    Deliberately anonymous: a warning only authenticated users can read is not a warning.
    This is what a broadcaster or a neighbouring warning system consumes.
    """
    row = await queries.get_alert(session, alert_id)
    if row is None or not row.get("cap_xml"):
        raise NotFound("No such alert.", context={"alert_id": str(alert_id)})

    return Response(
        content=row["cap_xml"],
        media_type="application/cap+xml",
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/alerts/feed.atom", response_class=Response)
async def alert_feed(session: SessionDep, limit: int = Query(default=50, ge=1, le=200)) -> Response:
    """An Atom feed of dispatched alerts. Public, for the same reason."""
    rows = await queries.list_dispatched(session, limit=limit)
    entries = "".join(
        "  <entry>\n"
        f"    <id>urn:sarana:alert:{row['id']}</id>\n"
        f"    <title>{_escape(row['headline'].get('en', 'Alert'))}</title>\n"
        f"    <updated>{row['created_at'].isoformat()}</updated>\n"
        f'    <link rel="alternate" type="application/cap+xml" '
        f'href="/api/v1/alerts/{row["id"]}/cap.xml"/>\n'
        "  </entry>\n"
        for row in rows
    )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <title>SARANA public alerts</title>\n"
        "  <id>urn:sarana:alerts</id>\n"
        f"{entries}"
        "</feed>\n"
    )
    return Response(content=feed, media_type="application/atom+xml")


async def _targets_for(alert: dict[str, Any], directory: HouseholdDirectory) -> list[Target]:
    """Who this alert is aimed at: every household in the area, resolved for real.

    Until the service-credential flow existed this returned one synthetic target per
    division, so every delivery number the platform produced was structurally correct and
    factually meaningless. It now reads `admin.household` through core-api under a
    credential holding `household:contact_read` and nothing else.

    **Households with no contact number are targeted anyway.** They come back with no
    hash, the fan-out records `NO_CHANNEL` against them, and they appear in
    `/alerts/{id}/delivery/gaps` as people who need a vehicle with a loudhailer. Dropping
    them here would report a division as fully covered when part of it cannot be reached
    at all, which is the precise failure the gaps endpoint exists to surface.

    **`preferred_language` comes from the household, not from their name.** Inferring
    language from a name is unreliable and goes wrong in exactly the communities most
    likely to be missed - the Ditwah failure this platform was built after.
    """
    codes = [str(code) for code in alert["area_gn_division_ids"]]
    contacts = await directory.contacts_for(codes)

    if not contacts:
        # An area with no households resolved. Almost always a misconfigured credential or
        # an area selection that matched nothing, and either way dispatching to nobody
        # while reporting success is the worst available outcome.
        _log.warning(
            "alert_targets_empty",
            divisions=len(codes),
            impact="this alert would reach nobody; check the area selection and that "
            "alerting-svc holds a household:contact_read credential",
        )

    # Deduplicated by contact hash. Two households sharing one handset - a common
    # arrangement in a village - are one phone, and sending the same evacuation order to it
    # twice is noise at the moment attention is scarcest. The delivery accounting already
    # counts by `target_ref_hash`, so the two would have collapsed there anyway; doing it
    # here means the message is sent once rather than counted once.
    #
    # Unreachable households key on their own id instead, so they never collapse: each one
    # is a separate person somebody has to go and find, and the gaps figure has to say how
    # many.
    seen: dict[str, Target] = {}
    for contact in contacts:
        key = contact.recipient_ref_hash or f"unreachable:{contact.household_id}"
        seen.setdefault(
            key,
            Target(
                target_ref_hash=key,
                gn_division_code=contact.gn_division_code,
                preferred_language=contact.preferred_language,
            ),
        )
    return list(seen.values())


def _summarise_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stored receipts. A target confirmed anywhere is confirmed once."""
    confirmed: set[str] = set()
    unconfirmed: set[str] = set()
    failed: set[str] = set()
    no_channel: set[str] = set()
    by_channel: dict[str, dict[str, int]] = {}
    by_language: dict[str, int] = {}

    for row in rows:
        channel = by_channel.setdefault(row["channel"], {})
        channel[row["status"]] = channel.get(row["status"], 0) + 1
        if row["status"] in {"SENT", "DELIVERED", "READ"}:
            confirmed.add(row["target_ref_hash"])
            by_language[row["language"]] = by_language.get(row["language"], 0) + 1
        elif row["status"] == "FAILED":
            failed.add(row["target_ref_hash"])
        elif row["status"] == "NO_CHANNEL":
            no_channel.add(row["target_ref_hash"])
        else:
            unconfirmed.add(row["target_ref_hash"])

    unconfirmed -= confirmed
    failed -= confirmed
    no_channel -= confirmed | unconfirmed | failed

    return {
        "targeted": len(confirmed | unconfirmed | failed | no_channel),
        "confirmed": len(confirmed),
        "unconfirmed": len(unconfirmed),
        "failed": len(failed),
        "no_channel": len(no_channel),
        "by_channel": by_channel,
        "by_language": by_language,
    }


def _sentence(summary: dict[str, Any]) -> str:
    return (
        f"{summary['confirmed']:,} of {summary['targeted']:,} targeted confirmed, "
        f"{summary['unconfirmed']:,} unconfirmed, {summary['failed']:,} failed, "
        f"{summary['no_channel']:,} with no channel available"
    )


def _escape(text_value: str) -> str:
    return (
        text_value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
