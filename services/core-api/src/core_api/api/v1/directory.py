"""Who holds which role, where.

The console's `/admin` screen names user and role administration and had no endpoint to
build it on. This is that endpoint, and the shape of it is a decision rather than a
translation of the tables.

**Reading is `admin:read`; granting and revoking are `system:admin` plus a fresh second
factor.** A role grant is how somebody acquires `disbursement:release`. It is the quietest
privilege escalation available on this platform and the one an attacker on an unattended
workstation would reach for, so it sits behind the same second factor the money gate does.

**The two human-gate scopes are never granted directly.** They arrive with a role, and
`sarana_shared.auth` refuses both to every machine principal whatever a row says. This
endpoint grants roles, never scopes, so there is no path through it that widens a
credential beyond a role somebody defined in code.

**A grant is scoped to an area, and the area is checked against the granter's own.** A
District administrator cannot grant a role in a district they do not hold. Permission and
area are two independent checks everywhere else in this platform, and role administration
is where forgetting that would be worst.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from core_api.api.deps import SessionDep
from sarana_shared.auth.dependencies import require
from sarana_shared.auth.principal import STEP_UP_WINDOW, Principal
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from sarana_shared.domain.admin import AdminCodeError, contains
from sarana_shared.domain.ids import uuid7
from sarana_shared.errors import Conflict, NotFound, Unauthenticated, ValidationFailed

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["directory"])

ReadPrincipal = Depends(require(Scope.ADMIN_READ))

# Granting a role is not a hierarchy read. `system:admin` is held by the ADMIN role alone.
AdminPrincipal = Depends(require(Scope.SYSTEM_ADMIN, allow_machine=False))

# `full_name` and `email` are selected here and nowhere else in this service. That is the
# distinction the conventions draw: `admin.household` never selects a citizen's name
# because nothing needs one, while a directory of *operators* whose whole purpose is
# saying who may release money is useless without saying who they are. No password hash,
# no phone hash and no MFA secret leaves this query.
_LIST_USERS = """
SELECT u.id::text, u.email, u.full_name, u.status, u.last_login_at, u.created_at,
       u.mfa_secret_encrypted IS NOT NULL AS mfa_enrolled,
       COALESCE(
           json_agg(
               json_build_object(
                   'grant_id', ur.id::text,
                   'role_code', r.code,
                   'role_name', r.name,
                   'scope_type', ur.scope_type,
                   'scope_code', ur.scope_code
               )
               ORDER BY r.code, ur.scope_code
           ) FILTER (WHERE ur.id IS NOT NULL),
           '[]'::json
       ) AS grants
FROM admin.app_user u
LEFT JOIN admin.user_role ur ON ur.user_id = u.id
LEFT JOIN admin.role r ON r.id = ur.role_id
WHERE (CAST(:status AS text) IS NULL OR u.status = CAST(:status AS text))
  AND (CAST(:role_code AS text) IS NULL OR r.code = CAST(:role_code AS text))
  AND (CAST(:query AS text) IS NULL
       OR u.full_name ILIKE '%' || CAST(:query AS text) || '%'
       OR u.email ILIKE '%' || CAST(:query AS text) || '%')
GROUP BY u.id
ORDER BY u.full_name NULLS LAST, u.email
LIMIT :limit OFFSET :offset
"""

_GET_ROLE = "SELECT id::text, code, name FROM admin.role WHERE code = :code"

_LIST_ROLES = "SELECT id::text, code, name FROM admin.role ORDER BY code"

_USER_EXISTS = "SELECT id::text, status FROM admin.app_user WHERE id = :user_id"

_INSERT_GRANT = """
INSERT INTO admin.user_role (id, user_id, role_id, scope_type, scope_code)
VALUES (:id, :user_id, :role_id, :scope_type, :scope_code)
ON CONFLICT (user_id, role_id, scope_code) DO NOTHING
RETURNING id::text
"""

_DELETE_GRANT = """
DELETE FROM admin.user_role
WHERE id = :grant_id AND user_id = :user_id
RETURNING id::text, scope_code
"""


class RoleGrant(BaseModel):
    """One role held by one user, within one administrative area."""

    model_config = ConfigDict(frozen=True)

    grant_id: str
    role_code: str
    role_name: dict[str, str]
    scope_type: str
    scope_code: str


class DirectoryUser(BaseModel):
    """An operator account and everything it can do.

    `scopes` is derived from the grants rather than stored, so what this endpoint reports
    and what a token actually carries come from the same `ROLE_SCOPES` table. A directory
    that listed permissions from a second source would eventually disagree with the tokens
    it describes, and the direction of that disagreement is unpredictable.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    email: str | None = None
    full_name: str | None = None
    status: str
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    mfa_enrolled: bool = Field(
        description="Whether a second factor is enrolled. Without one, no gate can be passed."
    )
    grants: list[RoleGrant] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)


class RoleDefinition(BaseModel):
    """A role and the scopes it carries, read from the code that enforces them."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    name: dict[str, str]
    scopes: list[str]
    grants_human_gate: bool = Field(
        description="True when this role carries dispatch:commit or disbursement:release."
    )


class GrantRequest(BaseModel):
    """Give a user a role in an area."""

    model_config = ConfigDict(extra="forbid")

    role_code: str = Field(max_length=32)
    scope_type: str = Field(max_length=16)
    scope_code: str = Field(max_length=16)
    reason: str = Field(
        min_length=3,
        max_length=500,
        description="Recorded in the audit trail. A grant with no stated reason is unreviewable.",
    )


def _scopes_for(grants: list[dict[str, Any]]) -> list[str]:
    """Every scope these grants add up to, sorted."""
    scopes: set[Scope] = set()
    for grant in grants:
        try:
            scopes |= ROLE_SCOPES[Role(grant["role_code"])]
        except (KeyError, ValueError):
            # A role code in the database that the code does not define. Skipped rather
            # than raised: the directory should still render, and the row is visible in
            # `grants` so the mismatch is findable rather than hidden behind a 500.
            _log.warning("unknown_role_code", role_code=grant.get("role_code"))
    return sorted(scope.value for scope in scopes)


def _assert_step_up(principal: Principal) -> None:
    """Refuse a grant without a fresh second factor.

    Uses `Principal.has_fresh_step_up` rather than reading the stamp, so this window and
    the two gates' window are the same constant. 401 rather than 403, for the same reason
    the gates use it: the caller holds the scope, and what is missing is proof of who is
    at the keyboard.
    """
    if principal.has_fresh_step_up():
        return
    minutes = int(STEP_UP_WINDOW.total_seconds() // 60)
    raise Unauthenticated(
        f"granting or revoking a role needs a second factor verified in the last {minutes} minutes",
        context={"reason": "step_up_required"},
    )


def _assert_within_own_area(principal: Principal, scope_code: str) -> None:
    """A granter may only grant inside an area they themselves hold.

    Segment-aware prefix containment on official codes, which is what row-level security
    does elsewhere rather than joining three levels of hierarchy on every row. A national
    administrator holds `LK` and is unaffected; a District one is held to their district.

    A malformed code raises rather than quietly covering nothing: a grant silently refused
    because the code was mistyped reads as a permissions problem and sends the
    administrator hunting in the wrong place.
    """
    areas = sorted(principal.area_codes)
    try:
        permitted = any(contains(area, scope_code) for area in areas)
    except AdminCodeError as error:
        raise ValidationFailed(str(error), context={"scope_code": scope_code}) from error
    if permitted:
        return
    raise ValidationFailed(
        f"you hold {', '.join(areas) or 'no areas'} and cannot grant a role in {scope_code}",
        context={"scope_code": scope_code, "granter_areas": areas},
    )


@router.get("/users", response_model=list[DirectoryUser])
async def list_users(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
    status: str | None = Query(default=None, max_length=16),
    role_code: str | None = Query(default=None, max_length=32),
    q: str | None = Query(default=None, max_length=120, description="Name or email substring."),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Any:
    """The operator directory, with what each account can do.

    Filtering by `role_code` answers the question this screen exists for: who can release
    money in this district, and is any of them enrolled for a second factor. An
    administrator who cannot answer that during an incident staffs the gate by guesswork.
    """
    result = await session.execute(
        text(_LIST_USERS),
        {
            "status": status,
            "role_code": role_code,
            "query": q,
            "limit": limit,
            "offset": offset,
        },
    )
    rows = [dict(row) for row in result.mappings()]
    for row in rows:
        row["scopes"] = _scopes_for(row.get("grants") or [])
    return rows


@router.get("/roles", response_model=list[RoleDefinition])
async def list_roles(
    session: SessionDep,
    principal: Principal = ReadPrincipal,
) -> Any:
    """Every role, with the scopes it carries.

    The scopes come from `ROLE_SCOPES` - the same table `require()` authorises against -
    rather than from a column. There is no second definition to drift, and a reviewer
    reading this screen is reading what the platform actually enforces.
    """
    result = await session.execute(text(_LIST_ROLES))
    rows = [dict(row) for row in result.mappings()]
    for row in rows:
        try:
            scopes = ROLE_SCOPES[Role(row["code"])]
        except (KeyError, ValueError):
            scopes = frozenset()
        row["scopes"] = sorted(scope.value for scope in scopes)
        row["grants_human_gate"] = bool(scopes & HUMAN_GATE_SCOPES)
    return rows


@router.post("/users/{user_id}/roles", response_model=DirectoryUser, status_code=201)
async def grant_role(
    user_id: UUID,
    body: GrantRequest,
    session: SessionDep,
    principal: Principal = AdminPrincipal,
) -> Any:
    """Give a user a role in an area. Requires a fresh second factor.

    The order of the checks is the safety argument: scope, then the second factor, then
    that the role exists in code and not only in the table, then that the granter holds the
    area. The write is last and the database's own CHECK on `scope_code ~ scope_type` is
    the line under all of it.

    Granting a role that carries a human gate is allowed and is logged as such. Refusing it
    here would push the work to psql, where nothing is audited - the useful control is that
    it is impossible to do quietly, not that it is impossible.
    """
    _assert_step_up(principal)

    try:
        role = Role(body.role_code)
    except ValueError as error:
        raise ValidationFailed(
            f"'{body.role_code}' is not a role this platform defines",
            context={"known": sorted(member.value for member in Role)},
        ) from error

    _assert_within_own_area(principal, body.scope_code)

    exists = (await session.execute(text(_USER_EXISTS), {"user_id": user_id})).mappings().first()
    if exists is None:
        raise NotFound("No such user.", context={"user_id": str(user_id)})

    row = (await session.execute(text(_GET_ROLE), {"code": body.role_code})).mappings().first()
    if row is None:
        raise Conflict(
            f"the role '{body.role_code}' is defined in code but has no row in admin.role; "
            "the seed has not been applied to this database",
            context={"role_code": body.role_code},
        )

    granted = await session.execute(
        text(_INSERT_GRANT),
        {
            "id": uuid7(),
            "user_id": user_id,
            "role_id": row["id"],
            "scope_type": body.scope_type,
            "scope_code": body.scope_code,
        },
    )
    already_held = granted.mappings().first() is None

    _log.info(
        "role_granted",
        user_id=str(user_id),
        role_code=body.role_code,
        scope_code=body.scope_code,
        granted_by=principal.subject_id,
        reason=body.reason,
        already_held=already_held,
        carries_human_gate=bool(ROLE_SCOPES[role] & HUMAN_GATE_SCOPES),
    )

    return await _one_user(session, user_id)


@router.delete("/users/{user_id}/roles/{grant_id}", response_model=DirectoryUser)
async def revoke_role(
    user_id: UUID,
    grant_id: UUID,
    session: SessionDep,
    principal: Principal = AdminPrincipal,
) -> Any:
    """Take a role away. Requires a fresh second factor.

    Revocation removes the grant rather than marking it inactive. The audit trail is where
    the history lives; a soft-deleted grant row is a permission that a query which forgot
    the filter would still honour, and that query is written eventually.
    """
    _assert_step_up(principal)

    removed = (
        (await session.execute(text(_DELETE_GRANT), {"grant_id": grant_id, "user_id": user_id}))
        .mappings()
        .first()
    )
    if removed is None:
        raise NotFound(
            "No such role grant on that user.",
            context={"user_id": str(user_id), "grant_id": str(grant_id)},
        )

    _log.info(
        "role_revoked",
        user_id=str(user_id),
        grant_id=str(grant_id),
        scope_code=removed["scope_code"],
        revoked_by=principal.subject_id,
    )
    return await _one_user(session, user_id)


async def _one_user(session: Any, user_id: UUID) -> dict[str, Any]:
    """Re-read one user so a caller sees the state its own write produced."""
    result = await session.execute(
        text(_LIST_USERS.replace("WHERE (", "WHERE u.id = :user_id AND (")),
        {
            "user_id": user_id,
            "status": None,
            "role_code": None,
            "query": None,
            "limit": 1,
            "offset": 0,
        },
    )
    row = result.mappings().first()
    if row is None:
        raise NotFound("No such user.", context={"user_id": str(user_id)})
    record = dict(row)
    record["scopes"] = _scopes_for(record.get("grants") or [])
    return record
