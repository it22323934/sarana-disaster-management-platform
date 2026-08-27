"""Service-to-service audit writes.

Mounted under `/internal/v1`, not `/api/v1`. The distinction is the point: a citizen's or
an officer's bearer token reaches the public surface, and nothing on the public surface
can append to the record of who did what. Entries arrive here from services that have
already decided something happened.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core_api.api.deps import SessionDep
from core_api.domain import audit_chain
from core_api.repo.audit import ACTOR_TYPES
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import Principal
from sarana_shared.auth.scopes import Scope

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal/v1", tags=["internal"])

# Only a machine principal writes audit entries. This is the same scope the event
# machinery uses, and it is never granted to a human-facing role.
InternalPrincipal = Depends(require(Scope.SYSTEM_ADMIN))


class AuditWriteRequest(BaseModel):
    """One entry to append.

    `before` and `after` arrive already redacted. The writing service is the only one that
    knows which of its own fields are personal data, and an audit entry has to be enough
    to reconstruct a decision without becoming a second copy of the data behind it.
    """

    model_config = ConfigDict(extra="forbid")

    actor_type: str = Field(description="AGENT, HUMAN or SYSTEM")
    action: str = Field(min_length=1, max_length=96)
    subject_type: str = Field(min_length=1, max_length=48)
    subject_id: str = Field(min_length=1, max_length=64)
    correlation_id: str = Field(min_length=1, max_length=64)

    actor_id: UUID | None = None
    agent_name: str | None = Field(default=None, max_length=64)
    langgraph_thread_id: str | None = Field(default=None, max_length=64)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _actor_is_identified(self) -> AuditWriteRequest:
        """Mirror the database CHECK, so a bad entry fails with a useful message.

        The constraint exists in both places on purpose: the database is what makes the
        rule true, and this is what makes the failure legible.
        """
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(f"actor_type must be one of {', '.join(sorted(ACTOR_TYPES))}")
        if self.actor_type == "AGENT" and not self.agent_name:
            raise ValueError("an AGENT action must name its agent")
        if self.actor_type == "HUMAN" and self.actor_id is None:
            raise ValueError("a HUMAN action must name the human")
        return self


class AuditWriteResponse(BaseModel):
    """Where the entry landed in the chain."""

    model_config = ConfigDict(frozen=True)

    id: str
    seq: int
    entry_hash: str


@router.post("/audit", response_model=AuditWriteResponse, status_code=status.HTTP_201_CREATED)
async def write_audit_entry(
    body: AuditWriteRequest,
    request: Request,
    session: SessionDep,
    principal: Principal = InternalPrincipal,
) -> Any:
    """Append one hash-chained entry.

    The chain is a database trigger, so the hash is computed where it cannot be skipped -
    not here, and not by whichever service happened to make the call.
    """
    row = await audit_chain.write_entry(
        session,
        actor_type=body.actor_type,
        actor_id=body.actor_id,
        agent_name=body.agent_name,
        action=body.action,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        correlation_id=body.correlation_id,
        langgraph_thread_id=body.langgraph_thread_id,
        before=json.dumps(body.before) if body.before is not None else None,
        after=json.dumps(body.after) if body.after is not None else None,
    )

    _log.info(
        "audit_entry_written",
        seq=row["seq"],
        action=body.action,
        subject_type=body.subject_type,
        actor_type=body.actor_type,
    )
    return {"id": row["id"], "seq": row["seq"], "entry_hash": row["entry_hash"]}
