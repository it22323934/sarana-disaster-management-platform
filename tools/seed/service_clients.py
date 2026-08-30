"""Provision the machine credentials services use to talk to each other.

Run:  uv run python tools/seed/service_clients.py

Replaces `tools/seed/service_token.py`, which minted a never-expiring token and printed it
for pasting into `.env`. That token could not be rotated without a redeploy, could not be
revoked at all, and carried every scope the SERVICE role had. What this writes instead is a
row in `admin.service_client`: a client id, an Argon2 hash of a secret, and the narrow set
of scopes that one service actually needs.

**The secret is printed once and never stored.** There is no recovery path. Rotating means
running this again with `--rotate`, which writes a new hash and prints a new secret; the old
one stops working on the next token request.

**Least privilege is the point of the file.** Each entry below lists the smallest set of
scopes that makes that service work. If a service starts failing on a permission, add the
scope here deliberately rather than widening the role — the role is the ceiling and it is
in code, not in this table.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core_api.domain.auth.password import PasswordHasherService
from core_api.domain.auth.service_clients import MIN_SECRET_LENGTH, ServiceClientConfig
from sarana_shared.auth.grants import ScopeType
from sarana_shared.auth.scopes import Scope
from sarana_shared.db.session import DatabaseSettings, create_engine
from sarana_shared.domain.ids import uuid7


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """One service's credential, and exactly why it holds what it holds."""

    client_id: str
    description: str
    scopes: frozenset[Scope]
    scope_type: ScopeType = ScopeType.NATIONAL
    scope_code: str = "LK"


# Every machine credential the platform issues. One entry per service, and the comment on
# each says what would break without the scope - so removing one is a decision somebody can
# make rather than a guess.
CLIENTS: Final[tuple[ClientSpec, ...]] = (
    ClientSpec(
        client_id="incident-svc",
        description=(
            "Resolves a citizen report's coordinate to a GN division on the intake path. "
            "Role.CITIZEN deliberately lacks admin:read, and citizens are the primary "
            "reporters, so the reporter's own token cannot be forwarded."
        ),
        # admin:read only. It resolves coordinates; it has no business reading resilience
        # data or invoking an agent, which the SERVICE role would otherwise have handed it.
        scopes=frozenset({Scope.ADMIN_READ}),
    ),
    ClientSpec(
        client_id="alerting-svc",
        description=(
            "Resolves a household to the keyed hash a message is addressed to, for the "
            "payment confirmation and reversal messages, and for real alert targeting."
        ),
        # The only credential that holds household:contact_read. Everything else that
        # reads the hierarchy keeps admin:read and cannot reach a per-person identifier.
        scopes=frozenset({Scope.ADMIN_READ, Scope.HOUSEHOLD_CONTACT_READ}),
    ),
    ClientSpec(
        client_id="gov-mock",
        description=(
            "The telco gateway submitting a citizen's SMS or USSD turn as an incident "
            "report. The sender is identified by an HMAC of their number; the gateway "
            "writes on their behalf."
        ),
        # incident:write and nothing else. It submits reports; it cannot read the
        # hierarchy, the graph, or anybody's contact details.
        scopes=frozenset({Scope.INCIDENT_WRITE}),
    ),
    ClientSpec(
        client_id="agent-svc",
        description=(
            "Reads the hierarchy and the Resilience Graph, and appends observations to it, "
            "on behalf of the forecasting and triage agents."
        ),
        scopes=frozenset(
            {Scope.ADMIN_READ, Scope.RESILIENCE_READ, Scope.RESILIENCE_WRITE, Scope.AGENT_INVOKE}
        ),
    ),
)

# Long enough that guessing is not a strategy, and machine-generated so there is no
# usability argument for anything shorter. `token_urlsafe(32)` is 256 bits.
SECRET_BYTES: Final = 32

_UPSERT = """
INSERT INTO admin.service_client
    (id, client_id, secret_hash, description, allowed_scopes, scope_type, scope_code, active)
VALUES (:id, :client_id, :secret_hash, :description,
        CAST(:allowed_scopes AS text[]), :scope_type, :scope_code, true)
ON CONFLICT (client_id) DO UPDATE
   SET description    = EXCLUDED.description,
       allowed_scopes = EXCLUDED.allowed_scopes,
       scope_type     = EXCLUDED.scope_type,
       scope_code     = EXCLUDED.scope_code,
       active         = true,
       updated_at     = now()
RETURNING client_id, (xmax = 0) AS created
"""

_ROTATE = """
UPDATE admin.service_client
   SET secret_hash = :secret_hash,
       rotated_at  = now(),
       updated_at  = now()
 WHERE client_id = :client_id
RETURNING client_id
"""


async def provision(engine: AsyncEngine, *, rotate: bool) -> list[tuple[str, str | None]]:
    """Create or update every credential. Returns `(client_id, secret or None)`.

    A secret is only generated when the row is new or `--rotate` was passed. Re-running
    this to update a description or a scope list must not silently invalidate a running
    service's credential, which is exactly what regenerating every secret would do.
    """
    hasher = PasswordHasherService.create()
    results: list[tuple[str, str | None]] = []

    async with engine.begin() as connection:
        for spec in CLIENTS:
            # Validated before it is written. A row that cannot be turned into a legal
            # grant should fail here, where somebody is watching, rather than at the
            # moment a service needs a token.
            ServiceClientConfig(
                client_id=spec.client_id,
                allowed_scopes=spec.scopes,
                scope_type=spec.scope_type,
                scope_code=spec.scope_code,
            )

            secret = secrets.token_urlsafe(SECRET_BYTES)
            if len(secret) < MIN_SECRET_LENGTH:  # pragma: no cover - 32 bytes is far above
                raise RuntimeError("generated secret is shorter than the minimum")

            row = await connection.execute(
                text(_UPSERT),
                {
                    "id": uuid7(),
                    "client_id": spec.client_id,
                    "secret_hash": hasher.hash(secret),
                    "description": spec.description,
                    "allowed_scopes": sorted(scope.value for scope in spec.scopes),
                    "scope_type": spec.scope_type.value,
                    "scope_code": spec.scope_code,
                },
            )
            created = bool(row.mappings().one()["created"])

            if created:
                results.append((spec.client_id, secret))
                continue

            if not rotate:
                # The upsert deliberately leaves `secret_hash` out of its DO UPDATE list,
                # so an existing credential keeps working. Re-running this to fix a
                # description or add a scope must not log a running service out.
                results.append((spec.client_id, None))
                continue

            fresh = secrets.token_urlsafe(SECRET_BYTES)
            await connection.execute(
                text(_ROTATE),
                {"client_id": spec.client_id, "secret_hash": hasher.hash(fresh)},
            )
            results.append((spec.client_id, fresh))

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="service-clients",
        description="Provision the machine credentials services authenticate with.",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="Owner DSN. These rows are administrative; sarana_app cannot write them.",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Issue a new secret for every existing client. The old ones stop working on "
        "the next token request, so restart the services with the new values.",
    )
    args = parser.parse_args(argv)

    engine = create_engine(
        DatabaseSettings(url=args.database_url, application_name="sarana-service-clients")
    )
    try:
        results = asyncio.run(provision(engine, rotate=args.rotate))
    finally:
        asyncio.run(engine.dispose())

    print("\nMachine credentials")
    print("=" * 72)
    for client_id, secret in results:
        if secret is None:
            print(f"  {client_id:<16} unchanged (pass --rotate to issue a new secret)")
            continue
        print(f"  {client_id:<16} {secret}")

    if any(secret for _, secret in results):
        print(
            "\nThese secrets are shown once and are not recoverable. Put them in the "
            "secret store, or in .env for local work:\n"
        )
        for client_id, secret in results:
            if secret is not None:
                variable = client_id.upper().replace("-", "_")
                print(f"  SARANA_{variable}_CLIENT_SECRET={secret}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
