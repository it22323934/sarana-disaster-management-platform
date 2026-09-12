"""FastAPI authorisation dependencies, shared by every service.

The shape a handler uses:

    @router.post("/entitlements/{entitlement_id}/approvals")
    async def approve(
        entitlement_id: UUID,
        principal: Principal = Depends(
            require(Scope.ENTITLEMENT_APPROVE_DS, area_from_path("entitlement_id"))
        ),
    ) -> ApprovalResponse: ...

The area resolver takes a path parameter and looks up the record's GN division. It never
reads an area from the request body: a caller who can name the area they are acting in
can name one they are allowed to act in.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final

import structlog
from fastapi import Request

from sarana_shared.auth.capability_guard import assert_capability_permits
from sarana_shared.auth.principal import Principal, StepUpRequired
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, Scope
from sarana_shared.errors import Unauthenticated

_log = structlog.get_logger(__name__)

# Resolves the administrative area a request is acting on. Returning None means the
# endpoint is not scoped to one record, so only the permission half is checked.
AreaResolver = Callable[[Request], Awaitable[str | None]]

PRINCIPAL_STATE_KEY: Final = "principal"


async def no_area(_request: Request) -> str | None:
    """Area resolver for endpoints that act on no particular record."""
    return None


def area_from_path(
    parameter: str, lookup: Callable[[Request, str], Awaitable[str | None]]
) -> AreaResolver:
    """Build a resolver that reads a path parameter and looks up its GN division.

    `lookup` is supplied by the service, because only the owning service knows how to get
    from an entitlement id to the division it belongs to. What is shared is the rule that
    the area comes from the stored record, never from the caller.
    """

    async def resolve(request: Request) -> str | None:
        raw = request.path_params.get(parameter)
        if raw is None:
            return None
        return await lookup(request, str(raw))

    return resolve


def area_from_query(parameter: str) -> AreaResolver:
    """Read an administrative code from a query parameter.

    Safe only for list endpoints, where the parameter narrows a result set that RBAC and
    row-level security have already restricted. It can never widen access: a caller who
    names a division they do not hold gets an empty page, not someone else's data.
    """

    async def resolve(request: Request) -> str | None:
        value = request.query_params.get(parameter)
        return value or None

    return resolve


def require(
    scope: Scope,
    area: AreaResolver = no_area,
    *,
    allow_machine: bool = True,
) -> Callable[[Request], Awaitable[Principal]]:
    """Build the dependency that authorises one endpoint.

    Runs four checks in the order that produces the most useful failure:

      1. A capability token is refused outright on anything but assessment drafting, so
         the field app gets "reconnect" rather than a permission error.
      2. Machine principals are refused on the two human gates, saying so plainly rather
         than looking like an expired step-up window.
      3. Permission and area, both of which must pass.
      4. Step-up, for the two gates only.

    Every denial is audited with actor, target and scope, and the response never names
    the record - a 403 that says which household is out of scope has just confirmed that
    household exists.
    """

    async def dependency(request: Request) -> Principal:
        principal: Principal | None = getattr(request.state, PRINCIPAL_STATE_KEY, None)
        if principal is None:
            raise Unauthenticated(
                "Authentication required.", context={"reason": "no_principal_on_request"}
            )

        area_code = await area(request)

        try:
            assert_capability_permits(principal, scope)

            if scope in HUMAN_GATE_SCOPES or not allow_machine:
                principal.assert_may_commit_gate(scope, area_code)
            else:
                principal.assert_can(scope, area_code)
        except StepUpRequired as exc:
            _audit_denial(request, principal, scope, area_code, reason="step_up_required")
            raise Unauthenticated(
                str(exc), context={"reason": "step_up_required", "scope": scope.value}
            ) from exc
        except Exception:
            _audit_denial(request, principal, scope, area_code, reason="forbidden")
            raise

        return principal

    return dependency


def _audit_denial(
    request: Request,
    principal: Principal,
    scope: Scope,
    area_code: str | None,
    *,
    reason: str,
) -> None:
    """Record a refused authorisation.

    Every 4xx from an authorisation check is audited with actor, target and scope.
    Repeated denials against ledger endpoints are what a security event is raised from,
    so the log line has to carry enough to spot a pattern without carrying the record.
    """
    _log.warning(
        "authorisation_denied",
        subject_id=principal.subject_id,
        required_scope=scope.value,
        area_code=area_code,
        path=request.url.path,
        method=request.method,
        token_kind="capability" if principal.is_offline_capability else "access",
        reason=reason,
    )
