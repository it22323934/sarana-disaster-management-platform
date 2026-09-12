"""The Principal: who is acting, what they may do, where, and how recently they proved it.

Handlers depend on this object and never on the raw token. Every authorisation question
the platform asks is answered here, so there is one place to read to know what the rules
are.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from sarana_shared.auth.grants import ScopeGrant, ScopeType
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, Role, Scope
from sarana_shared.domain.time import utc_now

# A session is not enough to commit a dispatch or release money. The principal must have
# re-proved possession of their TOTP device inside this window.
STEP_UP_WINDOW: Final = timedelta(minutes=5)


class StepUpRequired(Exception):
    """The action needs a fresh second factor that the principal has not provided.

    Deliberately not a `SaranaError` subclass here: `sarana_shared.errors` imports
    nothing from `auth`, and keeping the dependency pointing one way means the token
    layer stays usable without FastAPI. The API layer maps this to a 401.
    """

    def __init__(self, scope: Scope) -> None:
        super().__init__(
            f"{scope.value} requires a second factor verified within the last "
            f"{int(STEP_UP_WINDOW.total_seconds() // 60)} minutes"
        )
        self.scope = scope


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor.

    `grants` is the whole authorisation story: each one pairs a permission with the
    administrative area it was granted in. There is no separate list of permissions that
    could drift out of step with the areas they apply to.
    """

    subject_id: str
    roles: frozenset[Role]
    grants: frozenset[ScopeGrant]
    # The token this principal was built from. Recorded on audit entries and used to
    # revoke a single session without touching the rest of the device family.
    token_id: str = ""
    device_id: str | None = None
    # When the second factor was last verified. None means never in this session.
    step_up_at: datetime | None = None
    # True for agents and service principals. A human decision may never be attributed
    # to one, which is what keeps the two gates meaningful.
    is_machine: bool = False
    # Set only on the offline capability token carried by the Field Companion.
    is_offline_capability: bool = False
    _scopes: frozenset[Scope] = field(default_factory=frozenset, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_scopes", frozenset(grant.scope for grant in self.grants))

    @property
    def scopes(self) -> frozenset[Scope]:
        """Every permission held, ignoring area. For display and coarse checks only."""
        return self._scopes

    @property
    def area_codes(self) -> frozenset[str]:
        """Every administrative code this principal holds some grant in."""
        return frozenset(grant.scope_code for grant in self.grants)

    @property
    def is_national(self) -> bool:
        """Whether any grant is unrestricted."""
        return any(grant.scope_type is ScopeType.NATIONAL for grant in self.grants)

    def has_scope(self, scope: Scope) -> bool:
        """Whether the permission is held anywhere. Not sufficient on its own."""
        return scope in self._scopes

    def can(self, scope: Scope, area_code: str | None = None) -> bool:
        """Whether both halves pass: the permission, and the area if a record was named."""
        return any(grant.covers(scope, area_code) for grant in self.grants)

    def has_fresh_step_up(self, *, now: datetime | None = None) -> bool:
        """Whether a second factor was verified inside the step-up window."""
        if self.step_up_at is None:
            return False
        return (now or utc_now()) - self.step_up_at <= STEP_UP_WINDOW

    def assert_can(self, scope: Scope, area_code: str | None = None) -> None:
        """Raise Forbidden unless both halves pass.

        The message names the scope but never the record. A denial that says "household
        X is outside your area" has just told the caller that household X exists in a
        division they cannot see.
        """
        from sarana_shared.errors import Forbidden

        if self.can(scope, area_code):
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
                "held_grants": sorted(str(grant) for grant in self.grants),
            },
        )

    def assert_step_up(self, scope: Scope, *, now: datetime | None = None) -> None:
        """Raise StepUpRequired unless a second factor was verified recently enough.

        Called for the two mandatory human gates. A valid session is not enough: the
        person committing a dispatch or releasing money must prove, at that moment, that
        they still hold their second factor.

        Raises:
            StepUpRequired: if the window has lapsed or no factor was ever verified.
        """
        if scope not in HUMAN_GATE_SCOPES:
            return
        if not self.has_fresh_step_up(now=now):
            raise StepUpRequired(scope)

    def assert_may_commit_gate(
        self, scope: Scope, area_code: str | None = None, *, now: datetime | None = None
    ) -> None:
        """The full check for a human-gated action.

        Machine principals are refused outright rather than falling through to the
        step-up check: an agent has no second factor and never will, and the failure
        should say so plainly rather than looking like an expired window.
        """
        from sarana_shared.errors import Forbidden

        if scope in HUMAN_GATE_SCOPES and self.is_machine:
            raise Forbidden(
                "This action requires a human decision and cannot be taken by an agent "
                "or a service.",
                context={"subject_id": self.subject_id, "required_scope": scope.value},
            )
        if self.is_offline_capability:
            raise Forbidden(
                "An offline capability token authorises drafting assessments only.",
                context={"subject_id": self.subject_id, "required_scope": scope.value},
            )

        self.assert_can(scope, area_code)
        self.assert_step_up(scope, now=now)
