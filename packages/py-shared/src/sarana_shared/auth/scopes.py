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

from sarana_shared.domain.admin import AdminLevel, contains, level_of


class Scope(StrEnum):
    """A permission. Format is `{resource}:{action}`, lowercase, singular resource."""

    # Reference and common operating picture
    ADMIN_READ = "admin:read"
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
    """A named bundle of scopes. A principal may hold several."""

    CITIZEN = "citizen"
    GN_OFFICER = "gn_officer"
    DS_OFFICER = "ds_officer"
    DISTRICT_OFFICER = "district_officer"
    DMC_OPERATOR = "dmc_operator"
    RESPONDER = "responder"
    AUDITOR = "auditor"
    SYSTEM_ADMIN = "system_admin"
    # Machine principals. Agents run unattended and are deliberately denied both gates.
    AGENT = "agent"
    SERVICE = "service"


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
    Role.DS_OFFICER: frozenset(
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
    Role.DISTRICT_OFFICER: frozenset(
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
    Role.RESPONDER: frozenset(
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
    Role.SYSTEM_ADMIN: frozenset(Scope) - HUMAN_GATE_SCOPES,
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
class AreaScope:
    """The administrative area a principal may act within.

    `codes` are official admin codes at any level. National scope is the single code
    `LK`. A principal with no codes can act on nothing - that is the safe default, not
    an error state.
    """

    codes: frozenset[str]

    @classmethod
    def national(cls) -> AreaScope:
        """Unrestricted area scope. Held by DMC operators and system administrators."""
        return cls(codes=frozenset({"LK"}))

    @classmethod
    def of(cls, *codes: str) -> AreaScope:
        """Build an area scope, validating every code's shape up front."""
        for code in codes:
            level_of(code)
        return cls(codes=frozenset(codes))

    @property
    def is_national(self) -> bool:
        """Whether this scope covers the whole country."""
        return "LK" in self.codes

    def covers(self, target_code: str) -> bool:
        """Whether this principal may touch a record in `target_code`.

        Province codes are rejected by `contains`; expand them to districts through the
        reference table before building an AreaScope.
        """
        return any(contains(code, target_code) for code in self.codes)

    def narrowest_level(self) -> AdminLevel:
        """The finest level in this scope. Used to pick a sensible map default."""
        return max((level_of(code) for code in self.codes), key=lambda lvl: lvl.depth)


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is acting, what they may do, and where.

    Built from a verified JWT by `sarana_shared.auth.tokens`. Handlers depend on this,
    never on the raw token.
    """

    subject_id: str
    roles: frozenset[Role]
    scopes: frozenset[Scope]
    area: AreaScope
    # Set for machine principals. A human decision may never be attributed to one.
    is_machine: bool = False

    def has_scope(self, scope: Scope) -> bool:
        """Whether the permission half of the check passes."""
        return scope in self.scopes

    def can(self, scope: Scope, area_code: str | None = None) -> bool:
        """Whether both halves pass: permission, and area if a record was named."""
        if not self.has_scope(scope):
            return False
        if area_code is None:
            return True
        return self.area.covers(area_code)

    def assert_can(self, scope: Scope, area_code: str | None = None) -> None:
        """Raise Forbidden unless both halves pass.

        Raises:
            Forbidden: with a message that names the scope but never the record, so a
                denial does not itself disclose that the record exists.
        """
        from sarana_shared.errors import Forbidden

        if self.has_scope(scope) and (area_code is None or self.area.covers(area_code)):
            return

        detail = (
            f"This action requires the {scope.value} scope."
            if not self.has_scope(scope)
            else "This record is outside your assigned administrative area."
        )
        raise Forbidden(
            detail,
            context={
                "subject_id": self.subject_id,
                "required_scope": scope.value,
                "area_code": area_code,
            },
        )
