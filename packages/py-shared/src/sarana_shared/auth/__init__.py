"""Authentication and role-based access control."""

from sarana_shared.auth.scopes import (
    HUMAN_GATE_SCOPES,
    ROLE_SCOPES,
    AreaScope,
    Principal,
    Role,
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
    "HUMAN_GATE_SCOPES",
    "ROLE_SCOPES",
    "AreaScope",
    "Principal",
    "Role",
    "Scope",
    "TokenClaims",
    "TokenService",
    "TokenSettings",
    "bearer_token",
    "scopes_for_roles",
]
