"""The scope grant: a permission bound to an administrative area.

A grant is written `{resource}:{action}:{scope_type}:{scope_code}`, for example
`assessment:create:GN:LK-11-03-045` or `ledger:read:NATIONAL:*`.

Authorisation is two independent questions and both must pass: does the principal hold
this permission, and does their area cover the record being touched. Binding them into
one string keeps them together in the token, so a permission can never travel without the
area it was granted for.

**Codes, not UUIDs.** The area is the official administrative code rather than a database
id. Codes are hierarchical - a parent's code is a prefix of its child's - so a DISTRICT
grant covering its DS and GN descendants is a segment-aware prefix test needing no lookup
and no cache. It is also self-describing: a token in a log names the division it grants,
which matters when someone is working out why an approval was refused at 3am.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from sarana_shared.domain.admin import AdminCodeError, AdminLevel, level_of

# National grants use `*` rather than the code `LK`, so a reader can see at a glance that
# a grant is unrestricted rather than having to know that LK means the whole country.
NATIONAL_CODE: Final = "*"

_GRANT_PATTERN: Final = re.compile(
    r"^(?P<resource>[a-z_]+):(?P<action>[a-z_]+):(?P<scope_type>[A-Z]+):(?P<code>[^:]+)$"
)


class ScopeType(StrEnum):
    """The level an area grant is pinned at.

    Province is deliberately absent. It is not a level anyone holds an operational role
    at, and it is the one level whose containment cannot be decided from codes alone.
    """

    NATIONAL = "NATIONAL"
    DISTRICT = "DISTRICT"
    DS = "DS"
    GN = "GN"

    @property
    def admin_level(self) -> AdminLevel:
        """The hierarchy level this scope type pins to."""
        return _SCOPE_TYPE_LEVEL[self]


_SCOPE_TYPE_LEVEL: Final[dict[ScopeType, AdminLevel]] = {
    ScopeType.NATIONAL: AdminLevel.NATIONAL,
    ScopeType.DISTRICT: AdminLevel.DISTRICT,
    ScopeType.DS: AdminLevel.DS_DIVISION,
    ScopeType.GN: AdminLevel.GN_DIVISION,
}


class InvalidGrant(ValueError):
    """A grant string is malformed, or its code does not match its scope type."""


@dataclass(frozen=True, slots=True, order=True)
class ScopeGrant:
    """One permission, in one administrative area."""

    scope: Scope
    scope_type: ScopeType
    scope_code: str

    def __post_init__(self) -> None:
        if self.scope_type is ScopeType.NATIONAL:
            if self.scope_code != NATIONAL_CODE:
                raise InvalidGrant(
                    f"a NATIONAL grant must use {NATIONAL_CODE!r}, got {self.scope_code!r}"
                )
            return

        try:
            level = level_of(self.scope_code)
        except AdminCodeError as exc:
            raise InvalidGrant(str(exc)) from exc

        if level is not self.scope_type.admin_level:
            raise InvalidGrant(
                f"{self.scope_code!r} is a {level.value} code, but the grant claims "
                f"{self.scope_type.value}"
            )

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse `assessment:create:GN:LK-11-03-045`.

        Raises:
            InvalidGrant: if the shape is wrong, the permission is unknown, or the code
                does not match the claimed scope type.
        """
        match = _GRANT_PATTERN.match(value)
        if match is None:
            raise InvalidGrant(
                f"{value!r} is not a scope grant; expected "
                "{resource}:{action}:{scope_type}:{scope_code}"
            )

        permission = f"{match['resource']}:{match['action']}"
        try:
            scope = Scope(permission)
        except ValueError as exc:
            raise InvalidGrant(f"unknown permission {permission!r}") from exc

        try:
            scope_type = ScopeType(match["scope_type"])
        except ValueError as exc:
            raise InvalidGrant(f"unknown scope type {match['scope_type']!r}") from exc

        return cls(scope=scope, scope_type=scope_type, scope_code=match["code"])

    @classmethod
    def national(cls, scope: Scope) -> Self:
        """An unrestricted grant of one permission."""
        return cls(scope=scope, scope_type=ScopeType.NATIONAL, scope_code=NATIONAL_CODE)

    def covers(self, scope: Scope, area_code: str | None) -> bool:
        """Whether this grant authorises `scope` on a record in `area_code`.

        No scope is ever inherited upward: a GN grant never satisfies a DS or district
        target, however the codes relate.
        """
        if self.scope is not scope:
            return False
        if area_code is None:
            return True
        if self.scope_type is ScopeType.NATIONAL:
            return True
        # Segment-aware: the trailing hyphen is what stops LK-11-0 covering LK-11-03.
        return area_code == self.scope_code or area_code.startswith(f"{self.scope_code}-")

    def __str__(self) -> str:
        return f"{self.scope.value}:{self.scope_type.value}:{self.scope_code}"


def grants_for_assignment(
    role: Role, scope_type: ScopeType, scope_code: str
) -> frozenset[ScopeGrant]:
    """Expand one role assignment into the grants it confers.

    A user holding DS_APPROVER for `LK-11-03` gets every DS_APPROVER permission, each
    pinned to that DS division. Nothing reaches beyond it, and nothing reaches upward.
    """
    return frozenset(
        ScopeGrant(scope=scope, scope_type=scope_type, scope_code=scope_code)
        for scope in ROLE_SCOPES[role]
    )


def grants_for_assignments(
    assignments: Iterable[tuple[Role, ScopeType, str]],
) -> frozenset[ScopeGrant]:
    """Expand every role assignment a user holds into one grant set.

    Two assignments of the same role in different divisions produce two sets of grants,
    which is exactly right: a DS officer covering two divisions during a surge holds the
    permission twice, once per area, and loses one when that assignment ends.
    """
    grants: set[ScopeGrant] = set()
    for role, scope_type, scope_code in assignments:
        grants |= grants_for_assignment(role, scope_type, scope_code)
    return frozenset(grants)


def strip_human_gates(grants: frozenset[ScopeGrant]) -> frozenset[ScopeGrant]:
    """Remove the two mandatory human-gate permissions from a grant set.

    Applied to every machine principal at mint time, so no configuration mistake and no
    role misassignment can hand an agent the ability to commit a dispatch or release
    money. The autonomy model, expressed where it cannot be forgotten.
    """
    return frozenset(grant for grant in grants if grant.scope not in HUMAN_GATE_SCOPES)
