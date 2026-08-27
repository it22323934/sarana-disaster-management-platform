"""The offline capability token carried by the Field Companion.

Connectivity is the failure mode this platform exists to survive. A GN officer in a cut-off
division must be able to work for three days on nothing. The security answer to that is not
to make the app online-only - it is to make the offline credential capable of almost
nothing.

This token authorises exactly one thing: creating draft damage assessments, in one GN
division. It cannot approve an entitlement, cannot release funds, cannot read another
division, cannot read the incident queue. If the device is lost, what the finder gains is
the ability to write drafts that a DS officer will review before any of them turns into
money.

The app holds it in the platform secure enclave or Keystore. On reconnect the drafts sync
and the token is exchanged for a fresh one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sarana_shared.auth.grants import ScopeGrant, ScopeType
from sarana_shared.auth.scopes import Role, Scope
from sarana_shared.domain.admin import AdminLevel, level_of
from sarana_shared.domain.time import utc_now

# Three days. Long enough to cover a division cut off by a cyclone, short enough that a
# device stolen at the start of a response is useless before the response ends.
CAPABILITY_TTL: Final = timedelta(hours=72)

# The entire authority of this token. Deliberately a single permission: anything added
# here is something a lost, unlocked field device can do.
CAPABILITY_SCOPES: Final[frozenset[Scope]] = frozenset({Scope.ASSESSMENT_WRITE})


class NotAFieldOfficer(ValueError):
    """Only a GN officer, pinned to one GN division, may hold a capability token."""


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """A request to mint an offline token for one officer in one division."""

    subject_id: str
    gn_division_code: str
    device_id: str

    def __post_init__(self) -> None:
        if level_of(self.gn_division_code) is not AdminLevel.GN_DIVISION:
            raise NotAFieldOfficer(
                f"a capability token is pinned to a single GN division; "
                f"{self.gn_division_code!r} is not one"
            )
        if not self.device_id.strip():
            raise NotAFieldOfficer(
                "a capability token must be bound to a device, so a lost handset can be "
                "revoked without revoking the officer"
            )


def capability_grants(gn_division_code: str) -> frozenset[ScopeGrant]:
    """The grants a capability token carries: draft assessments, one division, nothing else."""
    return frozenset(
        ScopeGrant(scope=scope, scope_type=ScopeType.GN, scope_code=gn_division_code)
        for scope in CAPABILITY_SCOPES
    )


def may_hold_capability(roles: frozenset[Role]) -> bool:
    """Whether these roles permit an offline token at all.

    Only GN officers. An approver working offline would mean approvals accumulating on a
    device with no way to check them against the ledger, which is precisely the situation
    the two human gates exist to prevent.
    """
    return Role.GN_OFFICER in roles


def expires_at(*, issued_at: datetime | None = None) -> datetime:
    """When a capability token minted now stops being accepted."""
    return (issued_at or utc_now()) + CAPABILITY_TTL


def is_permitted_action(scope: Scope) -> bool:
    """Whether a capability token authorises this permission.

    Called by the authorisation dependency before any area check. A capability token is
    refused on every endpoint except assessment drafting, and the refusal says so rather
    than reporting a missing area.
    """
    return scope in CAPABILITY_SCOPES
