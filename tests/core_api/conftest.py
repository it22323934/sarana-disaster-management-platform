"""Fixtures for the core-api suite.

Runs against the real migrated database. The hierarchy endpoints are geometry queries and
row-level security is a database policy; neither proves anything against a mock.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from core_api.config import Settings
from core_api.main import build_app
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.scopes import Role
from sarana_shared.auth.tokens import TokenService, TokenSettings
from sarana_shared.domain.ids import uuid7
from sarana_shared.events.bus import BusKind
from tests.schema.conftest import (  # noqa: F401 - re-exported as fixtures
    REPO_ROOT,
    db,
    migrated_url,
    schema_engine,
)

HMAC_KEY = "11" * 32
CIPHER_KEY = "22" * 32

# One DS division in Kandy with two GN divisions whose boundaries touch. The geometry is
# synthetic but the codes follow the real shape, because the code prefix is what
# row-level security tests against.
CENTRAL_PROVINCE = "LK-P02"
KANDY_DISTRICT = "LK-11"
KANDY_DS = "LK-11-03"
GN_WEST = "LK-11-03-045"
GN_EAST = "LK-11-03-046"

# The two divisions are squares sharing the edge at longitude 80.7.
BOUNDARY_LON = 80.7
SOUTH_LAT = 7.2
NORTH_LAT = 7.3


@pytest.fixture(scope="session")
def core_settings(migrated_url: str) -> Settings:
    """Settings on the migrated database, with an in-process bus."""
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return Settings(
        database_url=migrated_url,
        jwt_public_key_path=keys / "jwt-public.pem",
        jwt_private_key_path=keys / "jwt-private.pem",
        pii_hmac_key=HMAC_KEY,
        pii_cipher_key=CIPHER_KEY,
        event_bus=BusKind.MEMORY,
        tracing_enabled=False,
    )


@pytest.fixture(scope="session")
def tokens(core_settings: Settings) -> TokenService:
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return TokenService(
        TokenSettings(
            public_key_path=keys / "jwt-public.pem",
            private_key_path=keys / "jwt-private.pem",
            issuer="https://sarana.lk",
            audience="sarana-api",
        )
    )


def _header(tokens: TokenService, role: Role) -> dict[str, str]:
    token = tokens.issue(
        str(uuid7()),
        roles=frozenset({role}),
        grants=grants_for_assignments([(role, ScopeType.NATIONAL, "*")]),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def operator_header(tokens: TokenService) -> dict[str, str]:
    """A DMC operator: reads the hierarchy and the graph."""
    return _header(tokens, Role.DMC_OPERATOR)


@pytest.fixture
def auditor_header(tokens: TokenService) -> dict[str, str]:
    """An auditor: reads the audit log."""
    return _header(tokens, Role.AUDITOR)


@pytest.fixture
def admin_header(tokens: TokenService) -> dict[str, str]:
    """A national admin: the only principal on the internal and projection endpoints."""
    return _header(tokens, Role.ADMIN)


@pytest.fixture
def citizen_header(tokens: TokenService) -> dict[str, str]:
    """A citizen: holds none of the scopes these endpoints require."""
    return _header(tokens, Role.CITIZEN)


@pytest_asyncio.fixture(loop_scope="session")
async def core_app(core_settings: Settings) -> AsyncIterator[FastAPI]:
    app = build_app(core_settings)
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def client(core_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=core_app)
    async with AsyncClient(transport=transport, base_url="http://core-api") as async_client:
        yield async_client


_INSERT_PROVINCE = """
INSERT INTO admin.province (id, code, name)
VALUES (:id, :code, CAST(:name AS jsonb))
"""

_INSERT_DISTRICT = """
INSERT INTO admin.district (id, code, province_id, name)
VALUES (:id, :code, :province_id, CAST(:name AS jsonb))
"""

_INSERT_DS = """
INSERT INTO admin.ds_division (id, code, district_id, name)
VALUES (:id, :code, :district_id, CAST(:name AS jsonb))
"""

_INSERT_GN = """
INSERT INTO admin.gn_division
    (id, code, ds_division_id, name, geom, population, household_count)
VALUES (
    :id, :code, :ds_id, CAST(:name AS jsonb),
    ST_Multi(ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)),
    :population, :households
)
"""


def _trilingual(label: str) -> str:
    return f'{{"si": "{label}", "ta": "{label}", "en": "{label}"}}'


@pytest_asyncio.fixture(loop_scope="session")
async def hierarchy_fixture(schema_engine: AsyncEngine) -> AsyncIterator[dict[str, str]]:
    """A province/district/DS/two-GN chain with real polygons.

    Committed for real rather than left in a rolled-back transaction: the endpoints read
    through the app's own sessions on their own connections, so rows this fixture could
    see but the app could not would prove nothing. Removed again on the way out, children
    first, so the foreign keys stay satisfied.
    """
    province_id = uuid7()
    district_id = uuid7()
    ds_id = uuid7()
    west_id = uuid7()
    east_id = uuid7()

    async with schema_engine.begin() as connection:
        await connection.execute(
            text(_INSERT_PROVINCE),
            {"id": province_id, "code": CENTRAL_PROVINCE, "name": _trilingual("Central")},
        )
        await connection.execute(
            text(_INSERT_DISTRICT),
            {
                "id": district_id,
                "code": KANDY_DISTRICT,
                "province_id": province_id,
                "name": _trilingual("Kandy"),
            },
        )
        await connection.execute(
            text(_INSERT_DS),
            {
                "id": ds_id,
                "code": KANDY_DS,
                "district_id": district_id,
                "name": _trilingual("Kandy Four Gravets"),
            },
        )
        for division_id, code, min_lon, max_lon, label in (
            (west_id, GN_WEST, 80.6, BOUNDARY_LON, "West"),
            (east_id, GN_EAST, BOUNDARY_LON, 80.8, "East"),
        ):
            await connection.execute(
                text(_INSERT_GN),
                {
                    "id": division_id,
                    "code": code,
                    "ds_id": ds_id,
                    "name": _trilingual(label),
                    "min_lon": min_lon,
                    "min_lat": SOUTH_LAT,
                    "max_lon": max_lon,
                    "max_lat": NORTH_LAT,
                    "population": 1200,
                    "households": 300,
                },
            )

    yield {
        "province_id": str(province_id),
        "district_id": str(district_id),
        "ds_division_id": str(ds_id),
        "west_id": str(west_id),
        "east_id": str(east_id),
        "west_code": GN_WEST,
        "east_code": GN_EAST,
    }

    async with schema_engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM admin.household WHERE gn_division_id = ANY(:ids)"),
            {"ids": [west_id, east_id]},
        )
        await connection.execute(
            text("DELETE FROM admin.gn_division WHERE id = ANY(:ids)"),
            {"ids": [west_id, east_id]},
        )
        await connection.execute(
            text("DELETE FROM admin.ds_division WHERE id = :id"), {"id": ds_id}
        )
        await connection.execute(
            text("DELETE FROM admin.district WHERE id = :id"), {"id": district_id}
        )
        await connection.execute(
            text("DELETE FROM admin.province WHERE id = :id"), {"id": province_id}
        )


@pytest_asyncio.fixture(loop_scope="session")
async def clean_resolve_cache(core_app: FastAPI) -> AsyncIterator[None]:
    """Empty the coordinate cache around a test.

    The cache is process-wide and lives for the app's lifespan, so a negative result
    cached by one test would otherwise be served to the next.
    """
    core_app.state.resolve_cache.clear()
    yield
    core_app.state.resolve_cache.clear()
