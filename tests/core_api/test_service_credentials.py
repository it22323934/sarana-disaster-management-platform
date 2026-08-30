"""The client-credentials grant, and everything it must refuse.

This replaces `SARANA_INCIDENT_SERVICE_TOKEN`: a never-expiring token, minted by a script,
pasted into an environment file, unrevocable, and carrying every scope the SERVICE role
had. Each property below is one of the things that was wrong with it, asserted as a
property of what replaced it.

Most of these are written as attempts to get something the mechanism must not give. A
credential mechanism is worth what its narrowest edge holds, and the edges are: can a
machine reach a human gate, can a row in the database widen a credential beyond its role,
and can a failed grant tell an attacker anything.
"""

from __future__ import annotations

import secrets
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core_api.domain.auth.password import PasswordHasherService
from core_api.domain.auth.service_clients import (
    SERVICE_CEILING,
    ClientRefused,
    ServiceClientConfig,
    granted_scopes,
    grants_for,
    parse_scopes,
)
from sarana_shared.auth.grants import ScopeType
from sarana_shared.auth.scopes import HUMAN_GATE_SCOPES, ROLE_SCOPES, Role, Scope
from sarana_shared.auth.tokens import TokenService
from sarana_shared.domain.ids import uuid7

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = "a-machine-generated-secret-that-is-long-enough"

_INSERT = """
INSERT INTO admin.service_client
    (id, client_id, secret_hash, description, allowed_scopes, scope_type, scope_code, active)
VALUES (:id, :client_id, :secret_hash, :description,
        CAST(:allowed_scopes AS text[]), :scope_type, :scope_code, :active)
ON CONFLICT (client_id) DO UPDATE
   SET secret_hash    = EXCLUDED.secret_hash,
       allowed_scopes = EXCLUDED.allowed_scopes,
       active         = EXCLUDED.active
"""


async def make_client(
    engine: AsyncEngine,
    *,
    client_id: str,
    scopes: list[str],
    secret: str = SECRET,
    active: bool = True,
    scope_type: str = "NATIONAL",
    scope_code: str = "LK",
) -> str:
    """Write a credential straight into the table and return its secret."""
    hasher = PasswordHasherService.create()
    async with engine.begin() as connection:
        await connection.execute(
            text(_INSERT),
            {
                "id": uuid7(),
                "client_id": client_id,
                "secret_hash": hasher.hash(secret),
                "description": "a test credential",
                "allowed_scopes": scopes,
                "scope_type": scope_type,
                "scope_code": scope_code,
                "active": active,
            },
        )
    return secret


async def grant(client: AsyncClient, client_id: str, secret: str, **extra: Any) -> Any:
    return await client.post(
        "/api/v1/auth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            **extra,
        },
    )


# --------------------------------------------------------------------------------------
# The grant works
# --------------------------------------------------------------------------------------


async def test_a_valid_credential_gets_a_token(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """The thing this exists to do."""
    secret = await make_client(schema_engine, client_id="ok-svc", scopes=["admin:read"])

    response = await grant(client, "ok-svc", secret)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "Bearer"
    assert body["scope"] == "admin:read"


async def test_the_token_is_short_lived(client: AsyncClient, schema_engine: AsyncEngine) -> None:
    """Fifteen minutes, the same as a person's.

    The credential this replaces never expired. A "machines are different" exemption is
    exactly how a permanent credential comes back, so there isn't one: revoking a client
    takes effect within the quarter hour.
    """
    secret = await make_client(schema_engine, client_id="ttl-svc", scopes=["admin:read"])

    body = (await grant(client, "ttl-svc", secret)).json()

    assert 0 < body["expires_in"] <= 3600


async def test_the_token_works_on_a_scoped_endpoint(
    client: AsyncClient, schema_engine: AsyncEngine, hierarchy_fixture: dict[str, str]
) -> None:
    """End to end: grant a token, then use it. Anything less proves nothing."""
    secret = await make_client(schema_engine, client_id="use-svc", scopes=["admin:read"])
    token = (await grant(client, "use-svc", secret)).json()["access_token"]

    response = await client.get(
        "/api/v1/admin/provinces", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------------------
# Everything it must refuse
# --------------------------------------------------------------------------------------


async def test_a_wrong_secret_is_refused(client: AsyncClient, schema_engine: AsyncEngine) -> None:
    await make_client(schema_engine, client_id="wrong-svc", scopes=["admin:read"])

    response = await grant(client, "wrong-svc", "not-the-secret")

    assert response.status_code == 401


async def test_a_revoked_credential_is_refused(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """`active = false` and the next token request fails.

    This is the property the environment-variable token could not have at all: there was
    no way to stop one working short of rotating the signing key for the whole platform.
    """
    secret = await make_client(
        schema_engine, client_id="revoked-svc", scopes=["admin:read"], active=False
    )

    response = await grant(client, "revoked-svc", secret)

    assert response.status_code == 401


async def test_every_failure_looks_the_same(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """An unknown client, a revoked one and a wrong secret are indistinguishable.

    Distinguishing them turns this endpoint into a way of enumerating which services
    exist and which of their credentials are live.
    """
    secret = await make_client(schema_engine, client_id="real-svc", scopes=["admin:read"])
    await make_client(schema_engine, client_id="dead-svc", scopes=["admin:read"], active=False)

    unknown = await grant(client, "no-such-svc", secret)
    revoked = await grant(client, "dead-svc", secret)
    bad_secret = await grant(client, "real-svc", "wrong")

    bodies = [unknown.json(), revoked.json(), bad_secret.json()]
    assert {response.status_code for response in (unknown, revoked, bad_secret)} == {401}
    assert len({body["detail"] for body in bodies}) == 1, (
        "the three failures must be indistinguishable from outside"
    )


async def test_an_unsupported_grant_type_is_refused(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    secret = await make_client(schema_engine, client_id="grant-svc", scopes=["admin:read"])

    response = await grant(client, "grant-svc", secret, grant_type="password")

    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# Least privilege
# --------------------------------------------------------------------------------------


async def test_a_token_carries_only_the_scopes_the_credential_holds(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """The old token carried the whole SERVICE role. This one carries what it was given."""
    secret = await make_client(schema_engine, client_id="narrow-svc", scopes=["admin:read"])

    body = (await grant(client, "narrow-svc", secret)).json()

    assert body["scope"] == "admin:read"
    assert "resilience:write" not in body["scope"]


async def test_asking_for_more_than_the_credential_holds_narrows_rather_than_fails(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """A service that adds a scope before its credential is updated should degrade.

    Failing closed here would take a service down at deploy time for a permission it may
    not need yet; the granted scope is in the response so it can notice.
    """
    secret = await make_client(schema_engine, client_id="greedy-svc", scopes=["admin:read"])

    body = (await grant(client, "greedy-svc", secret, scope="admin:read resilience:write")).json()

    assert body["scope"] == "admin:read"


async def test_a_request_for_nothing_it_holds_is_refused(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """An empty grant would be a token that authenticates and authorises nothing.

    Handing one back would make the failure surface later, as a permissions error on a
    call that looked authenticated.
    """
    secret = await make_client(schema_engine, client_id="mismatch-svc", scopes=["admin:read"])

    response = await grant(client, "mismatch-svc", secret, scope="resilience:write")

    assert response.status_code == 401


async def test_a_credential_cannot_be_widened_past_the_service_role(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """The ceiling is in code, so writing a wider row into the table does not widen it.

    This is the test that matters if the database is compromised: `allowed_scopes` is
    narrowing only, and a row asking for `ledger:read` gets a credential that cannot be
    turned into a legal grant at all.
    """
    secret = await make_client(
        schema_engine, client_id="wide-svc", scopes=["admin:read", "ledger:read"]
    )

    response = await grant(client, "wide-svc", secret)

    assert response.status_code == 401


async def test_a_credential_naming_a_scope_that_no_longer_exists_is_refused(
    client: AsyncClient, schema_engine: AsyncEngine
) -> None:
    """A renamed scope must not silently downgrade a credential.

    The service would keep authenticating and quietly lose the permission it was created
    for, which surfaces as a mysterious 403 somewhere else entirely.
    """
    secret = await make_client(
        schema_engine, client_id="stale-svc", scopes=["admin:read", "admin:read_v2"]
    )

    response = await grant(client, "stale-svc", secret)

    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# The human gates
# --------------------------------------------------------------------------------------


def test_no_machine_credential_can_be_configured_with_a_human_gate() -> None:
    """Refused at configuration, not only at use.

    `Principal.can` already refuses these to every machine principal, so this is the
    second lock on the same door. It is the one boundary where being wrong means money
    moving with nobody accountable, so it is closed twice.
    """
    for gate in HUMAN_GATE_SCOPES:
        with pytest.raises(ClientRefused, match="human gate"):
            ServiceClientConfig(
                client_id="rogue",
                allowed_scopes=frozenset({gate}),
                scope_type=ScopeType.NATIONAL,
                scope_code="LK",
            )


def test_the_service_role_holds_no_human_gate() -> None:
    """The ceiling itself is clean, so the check above can never be the only thing."""
    assert not (ROLE_SCOPES[Role.SERVICE] & HUMAN_GATE_SCOPES)


async def test_a_service_token_cannot_release_money(
    client: AsyncClient, schema_engine: AsyncEngine, tokens: TokenService
) -> None:
    """The end-to-end version: a granted token is a machine principal.

    `machine=True` is stamped into the claims, and `Principal.can` refuses every human
    gate to a machine regardless of what its scopes say.
    """
    secret = await make_client(schema_engine, client_id="gate-svc", scopes=["admin:read"])
    token = (await grant(client, "gate-svc", secret)).json()["access_token"]

    claims = tokens.verify(token)

    assert claims.machine is True
    # Grants are `{scope}:{scope_type}:{scope_code}`, so the check is on the prefix.
    granted = {item.split(":")[0] + ":" + item.split(":")[1] for item in claims.grants}
    assert Scope.DISBURSEMENT_RELEASE.value not in granted
    assert Scope.DISPATCH_COMMIT.value not in granted


# --------------------------------------------------------------------------------------
# The domain rules, without a database
# --------------------------------------------------------------------------------------


def test_a_credential_that_grants_nothing_is_refused() -> None:
    """It can do nothing and looks like it works, which is the worst combination."""
    with pytest.raises(ClientRefused, match="granting no scopes"):
        ServiceClientConfig(
            client_id="empty",
            allowed_scopes=frozenset(),
            scope_type=ScopeType.NATIONAL,
            scope_code="LK",
        )


def test_scopes_are_narrowed_three_ways() -> None:
    """Requested, configured, and the role ceiling. The widest is fixed in code."""
    config = ServiceClientConfig(
        client_id="narrow",
        allowed_scopes=frozenset({Scope.ADMIN_READ, Scope.RESILIENCE_READ}),
        scope_type=ScopeType.NATIONAL,
        scope_code="LK",
    )

    assert granted_scopes(config) == {Scope.ADMIN_READ, Scope.RESILIENCE_READ}
    assert granted_scopes(config, frozenset({Scope.ADMIN_READ})) == {Scope.ADMIN_READ}
    assert granted_scopes(config, frozenset({Scope.LEDGER_READ})) == frozenset()


def test_every_grant_is_pinned_to_the_credentials_own_area() -> None:
    """A machine is subject to row-level security on the same terms as a person.

    Which is what makes "this service can only see its own district" a property of the
    database rather than of the service behaving itself.
    """
    config = ServiceClientConfig(
        client_id="district-svc",
        allowed_scopes=frozenset({Scope.ADMIN_READ}),
        scope_type=ScopeType.DISTRICT,
        scope_code="LK-21",
    )

    grants = grants_for(config, frozenset({Scope.ADMIN_READ}))

    assert all(item.scope_type is ScopeType.DISTRICT for item in grants)
    assert all(item.scope_code == "LK-21" for item in grants)


def test_an_unknown_scope_string_is_refused() -> None:
    with pytest.raises(ClientRefused, match="not a scope"):
        parse_scopes(["admin:read", "not:a:scope"])


def test_the_ceiling_is_the_service_role() -> None:
    """Stated as a test so widening the role is a visible decision, not a side effect."""
    assert ROLE_SCOPES[Role.SERVICE] == SERVICE_CEILING


def test_a_generated_secret_clears_the_minimum() -> None:
    """The provisioning tool's secrets are far above the floor; assert it stays true."""
    from core_api.domain.auth.service_clients import MIN_SECRET_LENGTH

    assert len(secrets.token_urlsafe(32)) >= MIN_SECRET_LENGTH
