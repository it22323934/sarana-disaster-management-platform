"""Scopes and RBAC over the Sri Lanka administrative hierarchy.

Authorisation in SARANA is two independent questions, and both must pass:

  1. Permission - does this principal hold the scope for this action?
  2. Area       - does this principal's area cover the record being touched?

Keeping them separate is what stops a DS officer in Batticaloa from approving an
entitlement in Kandy just because their role is right. Area containment is a
segment-aware code prefix test (see `sarana_shared.domain.admin.contains`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class Scope(StrEnum):
    """A permission. Format is `{resource}:{action}`, lowercase, singular resource."""

    # Reference and common operating picture
    ADMIN_READ = "admin:read"
    # Reading one household's contact hash, so a message can be addressed to them.
    #
    # Separate from ADMIN_READ on purpose. `/admin/households` deliberately selects no
    # column that identifies a person - "nothing to redact is a stronger guarantee than
    # redacting" - and folding contact lookup into the same scope would quietly widen
    # every credential that only ever needed the hierarchy. This is the one permission
    # that reaches a stable per-person identifier, so it is the one that gets named.
    HOUSEHOLD_CONTACT_READ = "household:contact_read"
    RESILIENCE_READ = "resilience:read"
    RESILIENCE_WRITE = "resilience:write"

    # Anticipate
    FORECAST_READ = "forecast:read"
    FORECAST_WRITE = "forecast:write"

    # Warn
    ALERT_READ = "alert:read"
    ALERT_DRAFT = "alert:draft"
    ALERT_APPROVE = "alert:approve"
    ALERT_DISPATCH = "alert:dispatch"

    # Respond
    INCIDENT_READ = "incident:read"
    INCIDENT_WRITE = "incident:write"
    INCIDENT_VERIFY = "incident:verify"
    DISPATCH_PROPOSE = "dispatch:propose"
    DISPATCH_COMMIT = "dispatch:commit"

    # Sustain
    ASSESSMENT_READ = "assessment:read"
    ASSESSMENT_WRITE = "assessment:write"
    ENTITLEMENT_READ = "entitlement:read"
    ENTITLEMENT_CALCULATE = "entitlement:calculate"
    ENTITLEMENT_APPROVE_DS = "entitlement:approve_ds"
    ENTITLEMENT_APPROVE_DISTRICT = "entitlement:approve_district"
    DISBURSEMENT_READ = "disbursement:read"
    DISBURSEMENT_RELEASE = "disbursement:release"
    LEDGER_READ = "ledger:read"

    # Accountability
    GRIEVANCE_FILE = "grievance:file"
    GRIEVANCE_READ = "grievance:read"
    GRIEVANCE_RESOLVE = "grievance:resolve"
    ANOMALY_READ = "anomaly:read"
    ANOMALY_DISPOSE = "anomaly:dispose"
    AUDIT_READ = "audit:read"

    # Platform
    AGENT_INVOKE = "agent:invoke"
    SYSTEM_ADMIN = "system:admin"


# The two mandatory human gates. Nothing may hold these implicitly, no service principal
# may be granted them, and there is no bypass flag anywhere in the codebase.
HUMAN_GATE_SCOPES: Final[frozenset[Scope]] = frozenset(
    {Scope.DISPATCH_COMMIT, Scope.DISBURSEMENT_RELEASE}
)


class Role(StrEnum):
    """A named bundle of scopes. A principal may hold several.

    The values match the `code` CHECK on `admin.role` exactly. A role the database will
    not store is a role the platform cannot grant, so the two lists are the same list.
    """

    CITIZEN = "CITIZEN"
    GN_OFFICER = "GN_OFFICER"
    DS_APPROVER = "DS_APPROVER"
    DISTRICT_APPROVER = "DISTRICT_APPROVER"
    DMC_OPERATOR = "DMC_OPERATOR"
    DISPATCHER = "DISPATCHER"
    AUDITOR = "AUDITOR"
    ADMIN = "ADMIN"
    # Machine principals. Agents run unattended and are deliberately denied both gates.
    AGENT = "AGENT"
    SERVICE = "SERVICE"


# Role to scope mapping. Deliberately explicit and flat: a government IT reviewer must
# be able to read exactly what each role can do without following inheritance.
ROLE_SCOPES: Final[dict[Role, frozenset[Scope]]] = {
    Role.CITIZEN: frozenset(
        {
            Scope.ALERT_READ,
            Scope.INCIDENT_WRITE,
            Scope.GRIEVANCE_FILE,
        }
    ),
    Role.GN_OFFICER: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.ALERT_READ,
            Scope.FORECAST_READ,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_WRITE,
            Scope.INCIDENT_VERIFY,
            Scope.ASSESSMENT_READ,
            Scope.ASSESSMENT_WRITE,
            Scope.ENTITLEMENT_READ,
            Scope.GRIEVANCE_FILE,
            Scope.GRIEVANCE_READ,
            Scope.RESILIENCE_READ,
        }
    ),
    Role.DS_APPROVER: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.ALERT_READ,
            Scope.FORECAST_READ,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_VERIFY,
            Scope.ASSESSMENT_READ,
            Scope.ENTITLEMENT_READ,
            Scope.ENTITLEMENT_CALCULATE,
            Scope.ENTITLEMENT_APPROVE_DS,
            Scope.DISBURSEMENT_READ,
            Scope.LEDGER_READ,
            Scope.GRIEVANCE_READ,
            Scope.GRIEVANCE_RESOLVE,
            Scope.ANOMALY_READ,
            Scope.RESILIENCE_READ,
        }
    ),
    Role.DISTRICT_APPROVER: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.ALERT_READ,
            Scope.ALERT_DRAFT,
            Scope.ALERT_APPROVE,
            Scope.FORECAST_READ,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_VERIFY,
            Scope.DISPATCH_PROPOSE,
            Scope.DISPATCH_COMMIT,
            Scope.ASSESSMENT_READ,
            Scope.ENTITLEMENT_READ,
            Scope.ENTITLEMENT_APPROVE_DS,
            Scope.ENTITLEMENT_APPROVE_DISTRICT,
            Scope.DISBURSEMENT_READ,
            Scope.DISBURSEMENT_RELEASE,
            Scope.LEDGER_READ,
            Scope.GRIEVANCE_READ,
            Scope.GRIEVANCE_RESOLVE,
            Scope.ANOMALY_READ,
            Scope.ANOMALY_DISPOSE,
            Scope.RESILIENCE_READ,
        }
    ),
    Role.DMC_OPERATOR: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.ALERT_READ,
            Scope.ALERT_DRAFT,
            Scope.ALERT_APPROVE,
            Scope.ALERT_DISPATCH,
            Scope.FORECAST_READ,
            Scope.FORECAST_WRITE,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_VERIFY,
            Scope.DISPATCH_PROPOSE,
            Scope.DISPATCH_COMMIT,
            Scope.ASSESSMENT_READ,
            Scope.LEDGER_READ,
            Scope.GRIEVANCE_READ,
            Scope.ANOMALY_READ,
            Scope.RESILIENCE_READ,
        }
    ),
    Role.DISPATCHER: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.ALERT_READ,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_WRITE,
            Scope.RESILIENCE_READ,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.LEDGER_READ,
            Scope.DISBURSEMENT_READ,
            Scope.ENTITLEMENT_READ,
            Scope.ASSESSMENT_READ,
            Scope.GRIEVANCE_READ,
            Scope.ANOMALY_READ,
            Scope.AUDIT_READ,
        }
    ),
    Role.ADMIN: frozenset(Scope) - HUMAN_GATE_SCOPES,
    # Agents do everything except the two gates. That exclusion is the autonomy model
    # expressed in code rather than in a document.
    Role.AGENT: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.RESILIENCE_READ,
            Scope.RESILIENCE_WRITE,
            Scope.FORECAST_READ,
            Scope.FORECAST_WRITE,
            Scope.ALERT_READ,
            Scope.ALERT_DRAFT,
            Scope.ALERT_DISPATCH,
            Scope.INCIDENT_READ,
            Scope.INCIDENT_WRITE,
            Scope.INCIDENT_VERIFY,
            Scope.DISPATCH_PROPOSE,
            Scope.ASSESSMENT_READ,
            Scope.ENTITLEMENT_READ,
            Scope.ENTITLEMENT_CALCULATE,
            Scope.DISBURSEMENT_READ,
            Scope.LEDGER_READ,
            Scope.GRIEVANCE_READ,
            Scope.ANOMALY_READ,
            Scope.AGENT_INVOKE,
        }
    ),
    Role.SERVICE: frozenset(
        {
            Scope.ADMIN_READ,
            Scope.RESILIENCE_READ,
            Scope.RESILIENCE_WRITE,
            Scope.AGENT_INVOKE,
            # The ceiling, not the grant. An individual credential holds the subset it
            # needs; `admin.service_client.allowed_scopes` is what narrows it, and
            # alerting-svc is the only service that should be configured with this one.
            Scope.HOUSEHOLD_CONTACT_READ,
            # A telco gateway submitting a citizen's SMS as a report. The sender is
            # identified by an HMAC of their number, not by a credential, so the gateway
            # writes on their behalf - and only the gateway credential is configured with
            # this scope.
            Scope.INCIDENT_WRITE,
        }
    ),
}


def scopes_for_roles(roles: frozenset[Role] | set[Role] | list[Role]) -> frozenset[Scope]:
    """Union of the scopes granted by a set of roles."""
    granted: set[Scope] = set()
    for role in roles:
        granted |= ROLE_SCOPES[role]
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    """A role held at one administrative scope, as stored in `admin.user_role`.

    The unit the token minter reads. Expanding it into scope grants is
    `sarana_shared.auth.grants.grants_for_assignments`.
    """

    role: Role
    scope_type: str
    scope_code: str
