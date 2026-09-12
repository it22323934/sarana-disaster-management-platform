"""Fixtures for the gov-mock suite.

Two clients, and the difference matters:

`client` talks to a **quiet** app - every injection rate at zero. Almost every test wants
this, because a test that fails one time in twenty because chaos fired is a test nobody
trusts and everybody reruns.

`chaotic_client` is built per test with the injection you are exercising, and with the
timeout hold lowered so a timeout costs a fraction of a second rather than thirty.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from gov_mock.config import Settings
from gov_mock.main import build_app

# The seed every test asserts against. Fixing it here rather than taking the default means
# a change to the default is a visible test failure rather than a silent reshuffle of every
# generated household in the suite.
TEST_SEED = 20251128


@pytest.fixture(scope="session")
def public_key(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A placeholder key file. gov-mock verifies no tokens; the path just has to exist."""
    keys = tmp_path_factory.mktemp("keys")
    key = keys / "jwt-public.pem"
    key.write_text("", encoding="utf-8")
    return key


def build_settings(public_key: Path, **overrides: object) -> Settings:
    """Settings with chaos off unless a test asks for it."""
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://sarana:sarana@localhost:5432/sarana",
        "jwt_public_key_path": public_key,
        "tracing_enabled": False,
        "pii_hmac_key": "00" * 32,
        "pii_cipher_key": "11" * 32,
        "seed": TEST_SEED,
        "timeout_pct": 0.0,
        "error_pct": 0.0,
        "malformed_pct": 0.0,
        "stale_pct": 0.0,
        "latency_ms": 0,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings(public_key: Path) -> Settings:
    """Quiet settings: no injection, no latency."""
    return build_settings(public_key)


def _app_client(settings: Settings) -> AsyncClient:
    app = build_app(settings)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://gov-mock")


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """A client wired straight to the ASGI app.

    The lifespan is deliberately NOT run. gov-mock owns no tables and every route here is
    served from generated data or in-memory state, so opening a database engine and a Redis
    connection would make the whole suite depend on two containers it never queries.
    `services/gov-mock/tests/test_health.py` runs the lifespan for real; that is where the
    readiness wiring belongs.
    """
    async with _app_client(settings) as async_client:
        yield async_client


@pytest_asyncio.fixture
async def lifespan_client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """A client with the lifespan run, for the readiness checks that need it."""
    app = build_app(settings)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://gov-mock") as async_client,
    ):
        yield async_client


@pytest.fixture
def chaotic_client(public_key: Path) -> Callable[..., AsyncClient]:
    """Build a client whose app has one injection turned up.

    Returns a factory rather than a client so a test names exactly what it is injecting:

        async with chaotic_client(timeout_pct=100.0, timeout_hold_seconds=0.3) as chaos:
            ...

    The controller is configured directly rather than through `POST /mock/v1/chaos`,
    because a test that has to make a request to set up its own failure injection reads
    backwards. `test_chaos.py` covers the endpoint itself.
    """

    def build(**chaos: float) -> AsyncClient:
        app = build_app(build_settings(public_key))
        # Hold a timeout for a fraction of a second instead of thirty. The client's read
        # timeout is lowered to match in the tests that use it, so the client still gives
        # up first - which is the behaviour actually under test.
        settings: dict[str, float] = {"timeout_hold_seconds": 0.3, **chaos}
        app.state.mock.chaos.configure(**settings)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://gov-mock")

    return build
