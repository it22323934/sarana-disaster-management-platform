"""Why a dispatcher turned a plan down.

Shared because two services need the same taxonomy and neither may import the other's code:

  **incident-svc** enforces it on `POST /dispatch/{id}/reject` and stores it against a
  CHECK constraint.
  **agent-svc** offers it to the triage agent as the closed vocabulary a rejection must be
  recorded in, and records `OTHER` when the dispatcher gave no reason at all.

Rejections are the highest-value training signal the system produces, and free text cannot
be aggregated. Two copies of the list drift the moment somebody adds a reason on one side,
and the failure is silent: the agent offers a reason the API rejects, at the moment a
dispatcher is trying to say no to a plan.

`incident_svc.domain.dispatch_gate` re-exports `RejectionReason`, so the gate and its tests
read as though it still owns it.
"""

from __future__ import annotations

from enum import StrEnum


class RejectionReason(StrEnum):
    """Why a dispatcher turned a plan down.

    A fixed taxonomy, because rejections are the highest-value training signal the system
    produces and free text cannot be aggregated. `OTHER` still requires a note.
    """

    WRONG_PRIORITY = "wrong_priority"
    DUPLICATE = "duplicate"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    ALREADY_HANDLED = "already_handled"
    BAD_LOCATION = "bad_location"
    OTHER = "other"
