"""Mint a long-lived SERVICE token for local service-to-service calls.

Run:  python tools/seed/service_token.py

incident-svc calls core-api's `/admin/resolve` on the intake path. It does so as a
machine: a citizen holds `incident:write` and deliberately not `admin:read`, so forwarding
the reporter's token would fail for exactly the people who report the most.

In a deployment this credential comes from the secret store and rotates. This exists so a
laptop works, and the token it prints is only ever valid against the local dev keypair.
"""

from __future__ import annotations

from pathlib import Path

from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.scopes import Role
from sarana_shared.auth.tokens import TokenService, TokenSettings
from sarana_shared.domain.ids import uuid7

REPO_ROOT = Path(__file__).resolve().parents[2]
KEYS = REPO_ROOT / "infra" / "docker" / "dev-keys"


def main() -> int:
    service = TokenService(
        TokenSettings(
            public_key_path=KEYS / "jwt-public.pem",
            private_key_path=KEYS / "jwt-private.pem",
            issuer="https://sarana.lk",
            audience="sarana-api",
            # Long enough to outlast a working session without becoming permanent.
            access_ttl=__import__("datetime").timedelta(days=30),
        )
    )
    token = service.issue(
        str(uuid7()),
        roles=frozenset({Role.SERVICE}),
        grants=grants_for_assignments([(Role.SERVICE, ScopeType.NATIONAL, "LK")]),
        # A machine principal: the human gates are stripped at mint time regardless.
        machine=True,
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
