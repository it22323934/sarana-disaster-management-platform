"""The RBAC scope model shared by every service, per docs/build-prompts/05-auth-rbac.md.

A scope is `{resource}:{action}:{scope_type}:{scope_id}`, e.g.
`assessment:create:GN:0f2a...`, `ledger:read:NATIONAL:*`.

This module is pure matching logic — no database access. Resolving "which DS/District
does this GN belong to" (needed to check a DISTRICT-scoped grant against a GN-scoped
request) is core-api's job at token-mint time (file 05), cached, not looked up here per
request. Callers pass in the already-resolved ancestor chain.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ScopeType = Literal["GN", "DS", "DISTRICT", "NATIONAL"]

# Narrowest first — index is used to decide whether `a` is broader-or-equal to `b`.
_SCOPE_TYPE_ORDER: tuple[ScopeType, ...] = ("GN", "DS", "DISTRICT", "NATIONAL")


class Scope(BaseModel):
    """A single granted permission, as minted into a JWT's `scopes` claim."""

    resource: str  # e.g. "assessment", "entitlement", "ledger", "dispatch_plan"
    action: str  # e.g. "create", "read", "approve", "release"
    scope_type: ScopeType
    scope_id: str | None = None  # None only when scope_type == "NATIONAL"

    def __str__(self) -> str:
        sid = self.scope_id if self.scope_id is not None else "*"
        return f"{self.resource}:{self.action}:{self.scope_type}:{sid}"

    @classmethod
    def parse(cls, raw: str) -> Scope:
        try:
            resource, action, scope_type, scope_id = raw.split(":")
        except ValueError as exc:
            raise ValueError(f"Malformed scope string: {raw!r}") from exc
        if scope_type not in _SCOPE_TYPE_ORDER:
            raise ValueError(f"Unknown scope_type in {raw!r}: {scope_type!r}")
        return cls(
            resource=resource,
            action=action,
            scope_type=scope_type,
            scope_id=None if scope_id == "*" else scope_id,
        )


def _is_broader_or_equal(a: ScopeType, b: ScopeType) -> bool:
    return _SCOPE_TYPE_ORDER.index(a) >= _SCOPE_TYPE_ORDER.index(b)


def scope_satisfies(
    granted: Scope,
    *,
    resource: str,
    action: str,
    target_scope_type: ScopeType,
    target_scope_id: str,
    target_ancestor_ids: frozenset[str] = frozenset(),
) -> bool:
    """Does `granted` authorise `action` on `resource` for the given target?

    `target_ancestor_ids` is the target's own resolved ancestor chain (e.g. for a GN
    target: {ds_division_id, district_id}) — pass an empty set if the target IS a
    NATIONAL-scope operation with no narrower id.

    Rules (docs/build-prompts/05-auth-rbac.md):
    - A NATIONAL grant satisfies any narrower scope for the same resource+action.
    - A DISTRICT grant satisfies its DS and GN descendants.
    - No scope is ever inherited upward — a GN-scoped grant never satisfies a DS or
      broader target, regardless of ids.
    """
    if granted.resource != resource or granted.action != action:
        return False

    if granted.scope_type == "NATIONAL":
        return True

    if not _is_broader_or_equal(granted.scope_type, target_scope_type):
        return False  # e.g. a GN grant can never satisfy a DISTRICT-scope request

    if granted.scope_type == target_scope_type:
        return granted.scope_id == target_scope_id

    # granted is broader than the target (e.g. DISTRICT grant, GN target) — the target
    # must have the granted scope's id somewhere in its resolved ancestor chain.
    return granted.scope_id in target_ancestor_ids


def any_scope_satisfies(
    granted_scopes: list[Scope],
    *,
    resource: str,
    action: str,
    target_scope_type: ScopeType,
    target_scope_id: str,
    target_ancestor_ids: frozenset[str] = frozenset(),
) -> bool:
    return any(
        scope_satisfies(
            g,
            resource=resource,
            action=action,
            target_scope_type=target_scope_type,
            target_scope_id=target_scope_id,
            target_ancestor_ids=target_ancestor_ids,
        )
        for g in granted_scopes
    )
