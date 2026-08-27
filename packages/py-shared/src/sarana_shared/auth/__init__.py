"""Authentication and role-based access control.

Shared by every service. Other services verify tokens locally against the JWKS and never
call core-api per request - that would be a single point of failure during exactly the
event this platform exists for.
"""

from sarana_shared.auth.capability_guard import (
    CAPABILITY_SCOPES,
    assert_capability_permits,
)
from sarana_shared.auth.dependencies import (
    area_from_path,
    area_from_query,
    no_area,
    require,
)
from sarana_shared.auth.grants import (
    NATIONAL_CODE,
    InvalidGrant,
    ScopeGrant,
    ScopeType,
    grants_for_assignment,
    grants_for_assignments,
    strip_human_gates,
)
from sarana_shared.auth.jwks import (
    JWKS_PATH,
    JWKSCache,
    build_jwks,
    public_key_from_private,
)
from sarana_shared.auth.middleware import (
    AuthenticationMiddleware,
    apply_row_security_scope,
    is_anonymous_path,
)
from sarana_shared.auth.principal import (
    STEP_UP_WINDOW,
    Principal,
    StepUpRequired,
)
from sarana_shared.auth.scopes import (
    HUMAN_GATE_SCOPES,
    ROLE_SCOPES,
    Role,
    RoleAssignment,
    Scope,
    scopes_for_roles,
)
from sarana_shared.auth.tokens import (
    ALGORITHM,
    TokenClaims,
    TokenService,
    TokenSettings,
    bearer_token,
)

__all__ = [
    "ALGORITHM",
    "CAPABILITY_SCOPES",
    "HUMAN_GATE_SCOPES",
    "JWKS_PATH",
    "NATIONAL_CODE",
    "ROLE_SCOPES",
    "STEP_UP_WINDOW",
    "AuthenticationMiddleware",
    "InvalidGrant",
    "JWKSCache",
    "Principal",
    "Role",
    "RoleAssignment",
    "Scope",
    "ScopeGrant",
    "ScopeType",
    "StepUpRequired",
    "TokenClaims",
    "TokenService",
    "TokenSettings",
    "apply_row_security_scope",
    "area_from_path",
    "area_from_query",
    "assert_capability_permits",
    "bearer_token",
    "build_jwks",
    "grants_for_assignment",
    "grants_for_assignments",
    "is_anonymous_path",
    "no_area",
    "public_key_from_private",
    "require",
    "scopes_for_roles",
    "strip_human_gates",
]
