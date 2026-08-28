"""Delivery receipt webhooks.

A telco confirms handset delivery asynchronously, minutes after the send. This is what
turns a SENT receipt into DELIVERED - and it is the difference between "we handed 11,480
messages to a gateway" and "9,412 handsets confirmed".
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from alerting_svc.api.deps import SessionDep
from alerting_svc.repo import queries
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope
from sarana_shared.errors import ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["delivery"])

GatewayPrincipal = Depends(require(Scope.ALERT_DISPATCH))

# What a provider may tell us. Deliberately excludes NO_CHANNEL: that is this platform's
# conclusion about a person, not something a gateway is in a position to report.
ACCEPTED_STATUSES = frozenset({"DELIVERED", "READ", "FAILED", "EXPIRED", "UNKNOWN"})


class DlrCallback(BaseModel):
    """One provider's verdict on one message."""

    model_config = ConfigDict(extra="forbid")

    provider_ref: str = Field(max_length=128)
    status: str = Field(max_length=12)
    failure_reason: str | None = Field(default=None, max_length=500)


@router.post("/dlr/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def delivery_receipt(
    provider: str,
    body: DlrCallback,
    session: SessionDep,
    principal: Principal = GatewayPrincipal,
) -> Any:
    """Apply one delivery receipt.

    An unmatched `provider_ref` is accepted rather than refused. Gateways retry, reorder,
    and occasionally report on messages that have since expired; answering 4xx would make
    them retry harder for no benefit, and the receipt is not something we can act on
    anyway.
    """
    if body.status not in ACCEPTED_STATUSES:
        raise ValidationFailed(
            f"{body.status!r} is not a delivery status a provider can report; "
            f"expected one of {', '.join(sorted(ACCEPTED_STATUSES))}"
        )

    applied = await queries.apply_dlr(
        session,
        provider_ref=body.provider_ref,
        status=body.status,
        failure_reason=body.failure_reason,
    )

    if applied is None:
        _log.info("dlr_unmatched", provider=provider, provider_ref=body.provider_ref)
        return {"matched": False}

    _log.info(
        "dlr_applied",
        provider=provider,
        provider_ref=body.provider_ref,
        status=body.status,
    )
    return {"matched": True, "status": applied["status"]}
