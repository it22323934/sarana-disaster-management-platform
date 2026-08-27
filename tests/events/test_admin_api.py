"""The operator endpoints for replay and dead letters, exercised over HTTP.

The unit suites prove the rules hold in the coordinator and the DLQ module. These prove
the rules are actually reachable through the app: that the admin scope is enforced by the
wiring rather than only by the domain layer, that a refusal comes back as a status code an
operator's tooling can act on, and that the DLQ listing does not put failed events'
contents on a screen in an operations room.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core_api.config import Settings
from core_api.main import build_app
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.scopes import Role
from sarana_shared.auth.tokens import TokenService, TokenSettings
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now
from sarana_shared.events.bus import BusKind
from sarana_shared.events.dlq import record_failure
from sarana_shared.events.envelope import EventEnvelope
from sarana_shared.events.impl.in_memory import InMemoryEventBus
from tests.schema.conftest import REPO_ROOT

pytestmark = pytest.mark.asyncio(loop_scope="session")

HMAC_KEY = "11" * 32
CIPHER_KEY = "22" * 32
GROUP = "entitlement-calculator"
OTHER_GROUP = "alert-fanout"
KANDY_GN = "LK-11-03-045"


@pytest.fixture(scope="session")
def admin_settings(migrated_url: str) -> Settings:
    """Settings on the migrated database, with an in-process bus.

    The bus is in-memory so a redrive's republish is observable in the test rather than
    disappearing into Redis, and so the suite needs no broker to run.
    """
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
def admin_tokens(admin_settings: Settings) -> TokenService:
    """Mints the tokens these requests carry, using the dev keypair the app verifies."""
    keys = REPO_ROOT / "infra" / "docker" / "dev-keys"
    return TokenService(
        TokenSettings(
            public_key_path=keys / "jwt-public.pem",
            private_key_path=keys / "jwt-private.pem",
            issuer="https://sarana.lk",
            audience="sarana-api",
        )
    )


@pytest.fixture
def admin_header(admin_tokens: TokenService) -> dict[str, str]:
    """A national ADMIN, the only principal these endpoints accept."""
    token = admin_tokens.issue(
        str(uuid7()),
        roles=frozenset({Role.ADMIN}),
        grants=grants_for_assignments([(Role.ADMIN, ScopeType.NATIONAL, "LK")]),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def officer_header(admin_tokens: TokenService) -> dict[str, str]:
    """A real, valid principal who simply does not hold the admin scope."""
    token = admin_tokens.issue(
        str(uuid7()),
        roles=frozenset({Role.GN_OFFICER}),
        grants=grants_for_assignments([(Role.GN_OFFICER, ScopeType.GN, KANDY_GN)]),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(loop_scope="session")
async def admin_app(admin_settings: Settings) -> AsyncIterator[FastAPI]:
    """The built app with its lifespan run, so app.state is populated."""
    app = build_app(admin_settings)
    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def client(admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=admin_app)
    async with AsyncClient(transport=transport, base_url="http://core-api") as async_client:
        yield async_client


@pytest.fixture
def bus_of(admin_app: FastAPI) -> InMemoryEventBus:
    """The app's own bus, so a test sees exactly what the endpoint published."""
    bus = admin_app.state.event_bus
    assert isinstance(bus, InMemoryEventBus)
    bus.clear()
    return bus


def an_envelope(event_type: str = "sarana.aid.assessment.submitted") -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        producer="ledger-svc",
        correlation_id=uuid7(),
        payload={"assessment_id": str(uuid7()), "category": "HOUSE_FULL"},
    )


async def seed_dead_letter(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    group: str = GROUP,
    envelope: EventEnvelope | None = None,
) -> tuple[str, EventEnvelope]:
    """Commit one dead letter and return its id and envelope.

    Committed for real rather than left in a rolled-back transaction: the endpoint reads
    through its own session, so a row this test can see but the app cannot would prove
    nothing.
    """
    letter_envelope = envelope or an_envelope()
    async with session_factory() as session:
        try:
            raise RuntimeError("downstream calculator rejected the payload")
        except RuntimeError as error:
            letter = await record_failure(
                session,
                consumer_group=group,
                envelope=letter_envelope,
                error=error,
                attempt=5,
                traceback_text="Traceback (most recent call last): ...",
            )
        await session.commit()
        return str(letter.id), letter_envelope


# --------------------------------------------------------------------------------------
# Who may call these at all
# --------------------------------------------------------------------------------------


async def test_replay_refuses_an_anonymous_caller(client: AsyncClient) -> None:
    """A replay re-delivers history. It is never anonymous."""
    response = await client.post(
        "/api/v1/admin/replay",
        json={
            "since": (utc_now() - timedelta(days=1)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_replay_refuses_a_caller_without_the_admin_scope(
    client: AsyncClient, officer_header: dict[str, str]
) -> None:
    """A valid officer token is not an operator token."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=officer_header,
        json={
            "since": (utc_now() - timedelta(days=1)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 403


async def test_the_dlq_listing_refuses_an_anonymous_caller(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/dlq")

    assert response.status_code == 401


async def test_the_dlq_listing_refuses_a_caller_without_the_admin_scope(
    client: AsyncClient, officer_header: dict[str, str]
) -> None:
    response = await client.get("/api/v1/admin/dlq", headers=officer_header)

    assert response.status_code == 403


async def test_a_redrive_refuses_a_caller_without_the_admin_scope(
    client: AsyncClient, officer_header: dict[str, str]
) -> None:
    """Checked before the letter is looked up, so a 403 never doubles as an existence oracle."""
    response = await client.post(
        f"/api/v1/admin/dlq/{uuid7()}/redrive", headers=officer_header, json={}
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------------------
# Replay: it must name what it will touch
# --------------------------------------------------------------------------------------


async def test_a_replay_must_name_its_event_types(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """There is no replay-everything form, and the empty list is refused at the edge."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": (utc_now() - timedelta(days=1)).isoformat(),
            "event_types": [],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 422


async def test_a_replay_wider_than_the_guard_is_refused(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """Someone meant days and typed months. One retry costs less than a re-delivered disaster."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": (utc_now() - timedelta(days=200)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 422
    assert "allow_wide_window" in response.text


async def test_a_wide_window_is_allowed_when_explicitly_overridden(
    client: AsyncClient, admin_header: dict[str, str], bus_of: InMemoryEventBus
) -> None:
    """Occasionally the wide window is genuinely meant. It has to be said out loud."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": (utc_now() - timedelta(days=200)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
            "allow_wide_window": True,
        },
    )

    assert response.status_code == 200


async def test_a_replay_reports_its_scope_and_counts(
    client: AsyncClient, admin_header: dict[str, str], bus_of: InMemoryEventBus
) -> None:
    """The response names exactly what ran, including what consumers declined."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": (utc_now() - timedelta(days=1)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_group"] == GROUP
    assert body["event_types"] == ["sarana.aid.assessment.submitted"]
    assert body["delivered"] >= 0
    assert body["refused"] >= 0, "a refusal count is reported, not hidden"
    assert body["replay_id"]


async def test_a_replay_window_that_ends_before_it_begins_is_refused(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": utc_now().isoformat(),
            "until": (utc_now() - timedelta(days=2)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
        },
    )

    assert response.status_code == 422


async def test_an_unknown_field_on_a_replay_is_refused(
    client: AsyncClient, admin_header: dict[str, str]
) -> None:
    """extra="forbid": a misspelled guard must not be silently ignored."""
    response = await client.post(
        "/api/v1/admin/replay",
        headers=admin_header,
        json={
            "since": (utc_now() - timedelta(days=1)).isoformat(),
            "event_types": ["sarana.aid.assessment.submitted"],
            "target_group": GROUP,
            "allow_wide_windows": True,
        },
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# The DLQ listing
# --------------------------------------------------------------------------------------


async def test_the_dlq_listing_shows_a_pending_letter(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    clean_outbox: None,
) -> None:
    letter_id, envelope = await seed_dead_letter(session_factory)

    response = await client.get("/api/v1/admin/dlq", headers=admin_header)

    assert response.status_code == 200
    rows = response.json()
    match = [row for row in rows if row["id"] == letter_id]
    assert len(match) == 1
    assert match[0]["consumer_group"] == GROUP
    assert match[0]["event_type"] == envelope.event_type
    assert match[0]["attempts"] == 5
    assert "downstream calculator rejected the payload" in match[0]["last_error"]


async def test_the_dlq_listing_does_not_expose_the_failed_payload(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    clean_outbox: None,
) -> None:
    """A DLQ dashboard is read in an operations room. It shows what failed, not its contents."""
    _, envelope = await seed_dead_letter(session_factory)

    response = await client.get("/api/v1/admin/dlq", headers=admin_header)

    assert response.status_code == 200
    rows = response.json()
    assert rows, "expected the seeded letter"
    for row in rows:
        assert "envelope" not in row
        assert "payload" not in row
        assert "failures" not in row
    assert envelope.payload["assessment_id"] not in response.text


async def test_the_dlq_listing_filters_by_consumer_group(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    clean_outbox: None,
) -> None:
    mine, _ = await seed_dead_letter(session_factory, group=GROUP)
    theirs, _ = await seed_dead_letter(session_factory, group=OTHER_GROUP)

    response = await client.get(
        "/api/v1/admin/dlq", headers=admin_header, params={"consumer_group": GROUP}
    )

    assert response.status_code == 200
    returned = {row["id"] for row in response.json()}
    assert mine in returned
    assert theirs not in returned


# --------------------------------------------------------------------------------------
# Redrive
# --------------------------------------------------------------------------------------


async def test_a_redrive_republishes_the_original_event(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    bus_of: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """The stored envelope is enough on its own: nothing else is needed to retry."""
    letter_id, envelope = await seed_dead_letter(session_factory)

    response = await client.post(
        f"/api/v1/admin/dlq/{letter_id}/redrive",
        headers=admin_header,
        json={"note": "calculator fixed in 1.4.2"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "republished"
    assert response.json()["event_id"] == str(envelope.event_id)

    published = [seen.event_id for seen in bus_of.published]
    assert envelope.event_id in published, "the event must actually reach the bus"


async def test_a_redriven_letter_leaves_the_pending_list(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    bus_of: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """Otherwise the queue never empties and the alarm never clears."""
    letter_id, _ = await seed_dead_letter(session_factory)

    await client.post(f"/api/v1/admin/dlq/{letter_id}/redrive", headers=admin_header, json={})

    listing = await client.get("/api/v1/admin/dlq", headers=admin_header)
    assert letter_id not in {row["id"] for row in listing.json()}


async def test_a_redrive_of_an_unknown_letter_is_not_found(
    client: AsyncClient, admin_header: dict[str, str], bus_of: InMemoryEventBus
) -> None:
    response = await client.post(
        f"/api/v1/admin/dlq/{uuid7()}/redrive", headers=admin_header, json={}
    )

    assert response.status_code == 404
    assert bus_of.published == [], "nothing may be published for a letter that does not exist"


async def test_a_letter_cannot_be_redriven_twice(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    bus_of: InMemoryEventBus,
    clean_outbox: None,
) -> None:
    """A second redrive is an operator double-click, not a second delivery."""
    letter_id, envelope = await seed_dead_letter(session_factory)

    first = await client.post(
        f"/api/v1/admin/dlq/{letter_id}/redrive", headers=admin_header, json={}
    )
    assert first.status_code == 202

    second = await client.post(
        f"/api/v1/admin/dlq/{letter_id}/redrive", headers=admin_header, json={}
    )

    assert second.status_code == 404
    assert "already redriven" in second.text
    assert [seen.event_id for seen in bus_of.published].count(envelope.event_id) == 1


async def test_a_redrive_note_is_length_limited(
    client: AsyncClient,
    admin_header: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    clean_outbox: None,
) -> None:
    letter_id, _ = await seed_dead_letter(session_factory)

    response = await client.post(
        f"/api/v1/admin/dlq/{letter_id}/redrive",
        headers=admin_header,
        json={"note": "x" * 501},
    )

    assert response.status_code == 422
