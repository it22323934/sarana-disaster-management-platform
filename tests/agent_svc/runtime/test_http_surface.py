"""The HTTP surface: starting runs, answering them, and the approval inbox.

Written after two bugs that only an HTTP-level test could find.

**agent-svc mounted no authentication middleware**, so every endpoint returned 401 with a
principal that was never attached. The same gap existed in ledger-svc, where it made the
whole authenticated ledger surface — including the disbursement human gate — unreachable.
Both services' `deps.py` carried a comment saying the principal is "set by
AuthenticationMiddleware", and neither mounted it. Domain and schema tests cannot see this.

**The approval inbox returned an empty list** while a run sat interrupted. The pause is
LangGraph's mechanism, not ours, so nothing ever wrote our own `interrupt_payload` field —
only `graph.aget_state()` knows. An inbox that is quietly empty is the worst possible
failure of a human-gate design: the gates hold, and nobody can see what they are holding.

The scope split is the other thing under test here. Machines start agents; only people
answer them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from agent_svc.config import Settings
from agent_svc.main import build_app
from sarana_shared.auth.grants import ScopeType, grants_for_assignments
from sarana_shared.auth.scopes import Role
from sarana_shared.auth.tokens import TokenService, TokenSettings
from sarana_shared.domain.ids import uuid7

REPO_ROOT = Path(__file__).resolve().parents[3]
KEYS = REPO_ROOT / "infra" / "docker" / "dev-keys"


@pytest.fixture(scope="module")
def tokens() -> TokenService:
    return TokenService(
        TokenSettings(
            public_key_path=KEYS / "jwt-public.pem",
            private_key_path=KEYS / "jwt-private.pem",
            issuer="https://sarana.lk",
            audience="sarana-api",
        )
    )


def header(tokens: TokenService, role: Role) -> dict[str, str]:
    token = tokens.issue(
        str(uuid7()),
        roles=frozenset({role}),
        grants=grants_for_assignments([(role, ScopeType.NATIONAL, "LK")]),
        machine=role in (Role.AGENT, Role.SERVICE),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """The service, with an in-process checkpointer and no model provider.

    No database: the lifespan opens an engine but the readiness probe failing is not fatal,
    and none of these endpoints touch a SARANA table. A suite that needed Postgres to check
    an approval inbox is one nobody runs before pushing.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://sarana:sarana@localhost:5432/sarana",
        jwt_public_key_path=KEYS / "jwt-public.pem",
        jwt_private_key_path=KEYS / "jwt-private.pem",
        pii_hmac_key="00" * 32,
        pii_cipher_key="11" * 32,
        tracing_enabled=False,
        durable_checkpoints=False,
        event_bus="memory",
    )
    app = build_app(settings)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://agent-svc") as async_client,
    ):
        yield async_client


async def start(client: AsyncClient, headers: dict[str, str], subject: str, text: str):
    return await client.post(
        "/api/v1/agents/noop/runs",
        headers=headers,
        json={"subject_id": subject, "input": {"text": text}},
    )


# --------------------------------------------------------------------------------------
# Authentication is actually mounted
# --------------------------------------------------------------------------------------


async def test_an_unauthenticated_request_is_refused(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents")

    assert response.status_code == 401


async def test_an_authenticated_request_reaches_the_handler(
    client: AsyncClient, tokens: TokenService
) -> None:
    """The regression guard for the missing middleware.

    Without `AuthenticationMiddleware` mounted, this is 401 forever and every endpoint on
    the service is unreachable while looking perfectly well configured.
    """
    response = await client.get("/api/v1/agents", headers=header(tokens, Role.DISPATCHER))

    assert response.status_code == 200
    assert "noop" in [agent["name"] for agent in response.json()]


async def test_every_agent_says_what_it_does_in_a_blackout(
    client: AsyncClient, tokens: TokenService
) -> None:
    """The first question an operator asks when the model provider is down.

    On the list rather than in a docstring, because the answer differs per agent and
    nobody reads source during an incident.
    """
    agents = (await client.get("/api/v1/agents", headers=header(tokens, Role.ADMIN))).json()

    for agent in agents:
        assert agent["degraded"].strip(), f"{agent['name']} does not say what it degrades to"


# --------------------------------------------------------------------------------------
# Running and resuming
# --------------------------------------------------------------------------------------


async def test_a_confident_run_completes_without_a_human(
    client: AsyncClient, tokens: TokenService
) -> None:
    response = await start(client, header(tokens, Role.ADMIN), "r1", "there is a FLOOD here")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["output"]["category"] == "flood"
    # Labelled, always. A rule presented as a judgement is a lie about how the decision
    # was made, and the person reading it decides differently depending on which it was.
    assert body["output"]["provenance"] == "DETERMINISTIC"


async def test_an_unsure_run_pauses_and_says_what_it_is_asking(
    client: AsyncClient, tokens: TokenService
) -> None:
    response = await start(client, header(tokens, Role.ADMIN), "r2", "please help us")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "INTERRUPTED"
    assert body["interrupt"]["subject_id"] == "r2"
    assert body["interrupt"]["question"]


async def test_the_thread_id_is_derived_from_the_subject(
    client: AsyncClient, tokens: TokenService
) -> None:
    """So a resume never has to look one up, and a retry does not fork a second approval."""
    response = await start(client, header(tokens, Role.ADMIN), "r3", "flood")

    assert response.json()["thread_id"] == "noop:report:r3"


async def test_starting_the_same_subject_twice_does_not_fork(
    client: AsyncClient, tokens: TokenService
) -> None:
    """A retried webhook must not put a second identical approval in front of a second
    officer."""
    admin = header(tokens, Role.ADMIN)
    first = await start(client, admin, "r4", "please help")
    second = await start(client, admin, "r4", "please help")

    assert first.json()["thread_id"] == second.json()["thread_id"]

    inbox = (
        await client.get(
            "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.DISPATCHER)
        )
    ).json()
    matching = [item for item in inbox if item["subject_id"] == "r4"]
    assert len(matching) == 1, "one subject must produce one pending approval"


async def test_a_person_can_answer_and_the_run_finishes(
    client: AsyncClient, tokens: TokenService
) -> None:
    started = await start(client, header(tokens, Role.ADMIN), "r5", "please help")
    thread_id = started.json()["thread_id"]

    response = await client.post(
        f"/api/v1/agents/threads/{thread_id}/resume",
        headers=header(tokens, Role.DISPATCHER),
        json={
            "approved": True,
            "decided_by": "dispatcher@sarana.lk",
            "payload": {"category": "flood"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    # A human's answer is the answer, and downstream must not read it as the classifier's.
    assert body["output"]["provenance"] == "HUMAN"
    assert body["output"]["category"] == "flood"


async def test_resuming_a_finished_run_is_refused(
    client: AsyncClient, tokens: TokenService
) -> None:
    """Otherwise a double-click restarts work that already completed."""
    started = await start(client, header(tokens, Role.ADMIN), "r6", "there is a FLOOD")
    thread_id = started.json()["thread_id"]

    response = await client.post(
        f"/api/v1/agents/threads/{thread_id}/resume",
        headers=header(tokens, Role.DISPATCHER),
        json={"approved": True, "decided_by": "dispatcher@sarana.lk"},
    )

    assert response.status_code == 422


async def test_a_malformed_thread_id_is_a_clear_refusal(
    client: AsyncClient, tokens: TokenService
) -> None:
    """Not a 500 three lines later."""
    response = await client.get(
        "/api/v1/agents/threads/not-a-thread-id", headers=header(tokens, Role.DISPATCHER)
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# The approval inbox
# --------------------------------------------------------------------------------------


async def test_the_inbox_lists_runs_waiting_on_a_person(
    client: AsyncClient, tokens: TokenService
) -> None:
    """The regression guard for the empty-inbox bug.

    An inbox that is quietly empty while runs sit paused is the worst failure a
    human-gate design can have: the gates hold, and nobody can see what they are holding.
    """
    await start(client, header(tokens, Role.ADMIN), "r7", "please help us")

    response = await client.get(
        "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.DISPATCHER)
    )

    assert response.status_code == 200
    inbox = response.json()
    assert any(item["subject_id"] == "r7" for item in inbox), "the paused run is not listed"


async def test_every_inbox_entry_carries_the_question(
    client: AsyncClient, tokens: TokenService
) -> None:
    """A pending approval that does not say what it is about is one an officer cannot
    action without opening three other screens."""
    await start(client, header(tokens, Role.ADMIN), "r8", "unclear report")

    inbox = (
        await client.get(
            "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.DISPATCHER)
        )
    ).json()

    for item in inbox:
        assert item["status"] == "INTERRUPTED"
        assert item["interrupt"] is not None
        assert item["interrupt"]["question"]


async def test_a_completed_run_is_not_in_the_inbox(
    client: AsyncClient, tokens: TokenService
) -> None:
    """An inbox that accumulates finished work is one people stop reading."""
    await start(client, header(tokens, Role.ADMIN), "r9", "there is a FLOOD here")

    inbox = (
        await client.get(
            "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.DISPATCHER)
        )
    ).json()

    assert not any(item["subject_id"] == "r9" for item in inbox)


async def test_the_history_shows_how_the_run_got_there(
    client: AsyncClient, tokens: TokenService
) -> None:
    """For working out why an agent decided something, months later."""
    started = await start(client, header(tokens, Role.ADMIN), "r10", "there is a FLOOD")
    thread_id = started.json()["thread_id"]

    response = await client.get(
        f"/api/v1/agents/threads/{thread_id}/history", headers=header(tokens, Role.DISPATCHER)
    )

    assert response.status_code == 200
    assert len(response.json()) >= 1


# --------------------------------------------------------------------------------------
# The scope split
# --------------------------------------------------------------------------------------


async def test_a_machine_cannot_answer_its_own_gate(
    client: AsyncClient, tokens: TokenService
) -> None:
    """The property the whole human-in-the-loop design rests on.

    An agent resuming its own approval would make every gate in the platform decorative.
    Refused twice over: `agent:review` is held by no machine role, and the dependency
    refuses machine principals outright.
    """
    started = await start(client, header(tokens, Role.ADMIN), "r11", "please help")
    thread_id = started.json()["thread_id"]

    response = await client.post(
        f"/api/v1/agents/threads/{thread_id}/resume",
        headers=header(tokens, Role.AGENT),
        json={"approved": True, "decided_by": "agent"},
    )

    assert response.status_code == 403


async def test_a_dispatcher_can_open_the_inbox(client: AsyncClient, tokens: TokenService) -> None:
    """Before `agent:review` existed this was ADMIN-only, which would have left the people
    who actually answer these unable to open the queue."""
    response = await client.get(
        "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.DISPATCHER)
    )

    assert response.status_code == 200


async def test_a_citizen_cannot_see_the_inbox(client: AsyncClient, tokens: TokenService) -> None:
    """It names incidents and what the state is deciding about them."""
    response = await client.get(
        "/api/v1/agents/threads?status=interrupted", headers=header(tokens, Role.CITIZEN)
    )

    assert response.status_code == 403


async def test_an_unknown_agent_names_the_ones_that_exist(
    client: AsyncClient, tokens: TokenService
) -> None:
    """More useful than a bare 'not found' when somebody has mistyped a name."""
    response = await client.post(
        "/api/v1/agents/nosuch/runs",
        headers=header(tokens, Role.ADMIN),
        json={"subject_id": "x"},
    )

    assert response.status_code == 404
    assert "noop" in response.json()["detail"]
