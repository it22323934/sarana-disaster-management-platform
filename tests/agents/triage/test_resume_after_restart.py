"""A plan paused at the gate survives the process that made it.

Build file 16 names this file in its definition of done, and the property is the whole
reason the gate can be indefinite: a dispatcher does not have to answer within a request
timeout, or before a deploy, or at all. The graph pauses at zero cost and waits.

## What this file tests, and what it cannot

The build file's command is
`docker compose restart agent-svc && make test -- .../test_resume_after_restart.py`, which
needs a **durable** checkpointer — `AsyncPostgresSaver` over a live database. These tests
use the in-process saver and a *new graph object* per phase, which proves the half that is
this repository's own code: the thread id is derivable, the checkpoint carries everything
the resume needs, and no state is held in the compiled graph or in the closures around it.

What it does not prove is that Postgres round-trips the checkpoint. That needs the durable
saver and a container, `tests/agent_svc/runtime/test_interrupt_resume.py` covers the saver
itself, and `HANDOFF.md` records that the two halves have not been run end to end against a
restarted container.

Saying that plainly matters more than a green tick here would: the property is real and the
proof is partial.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import Command

from agent_svc.agents.triage import graph as triage
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state, thread_id_for
from tests.agents.triage.conftest import (
    NOW,
    FakeIncidents,
    FakePlanStore,
    FakeResponders,
    incident,
    responder,
)

SUBJECT = "plan-restart"
THREAD = thread_id_for("triage", "dispatch_plan", SUBJECT)


def compile_graph(checkpointer, store: FakePlanStore):
    """A fresh graph object over a shared checkpointer.

    Compiling again is what stands in for the restart: the new graph shares no Python
    state with the old one, so anything the resume needs has to have come out of the
    checkpoint.
    """
    return triage.build(
        checkpointer,
        incidents=FakeIncidents(queue=[incident("i1", people=2)]),
        responders=FakeResponders(crews=[responder("r1")]),
        store=store,
        now=NOW,
    )


async def test_a_paused_plan_resumes_on_a_graph_compiled_after_it_paused() -> None:
    """The half this repository's own code is responsible for.

    Everything the resume needs came out of the checkpoint, not out of the object that
    created it.
    """
    checkpointer = memory_checkpointer()
    store = FakePlanStore()
    config = config_for(THREAD)

    before = compile_graph(checkpointer, store)
    state = initial_state(
        agent="triage",
        subject_type="dispatch_plan",
        subject_id=SUBJECT,
        correlation_id="restart-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    paused = await before.ainvoke(state, config)

    assert paused["__interrupt__"]
    assert store.proposed

    # The restart. A new graph object, sharing nothing but the checkpointer.
    after = compile_graph(checkpointer, store)
    resumed = await after.ainvoke(
        Command(
            resume={
                "subject_id": SUBJECT,
                "decided_by": "dispatcher-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": True,
            }
        ),
        config,
    )

    assert resumed["status"] == "COMPLETED"
    assert resumed["output"]["released"] is True
    # The plan was written once, before the pause. The resume did not write a second one.
    assert len(store.proposed) == 1


async def test_the_thread_id_is_derivable_so_a_resume_never_has_to_search() -> None:
    """`{agent}:{subject_type}:{subject_id}`. A restarted process can reconstruct the thread
    from the plan row alone - `dispatch_plan.langgraph_thread_id` stores it, and this is the
    format it stores."""
    assert f"triage:dispatch_plan:{SUBJECT}" == THREAD


async def test_the_paused_state_carries_the_whole_approval_payload() -> None:
    """A dispatcher opening the inbox after a restart sees the same screen.

    If the payload were rebuilt from the closures rather than read from the checkpoint, it
    would be empty here - the fakes in the new graph are new objects.
    """
    checkpointer = memory_checkpointer()
    store = FakePlanStore()
    config = config_for(THREAD)

    before = compile_graph(checkpointer, store)
    state = initial_state(
        agent="triage",
        subject_type="dispatch_plan",
        subject_id=SUBJECT,
        correlation_id="restart-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    await before.ainvoke(state, config)

    after = compile_graph(checkpointer, store)
    snapshot = await after.aget_state(config)

    assert snapshot.next, "the thread is still paused"
    assert snapshot.values["plan"]["plan_id"]
    assert "factors" in snapshot.values["plan"]


async def test_a_rejection_also_survives_a_restart() -> None:
    """Both branches out of the gate, not only the happy one."""
    checkpointer = memory_checkpointer()
    store = FakePlanStore()
    config = config_for(THREAD)

    before = compile_graph(checkpointer, store)
    state = initial_state(
        agent="triage",
        subject_type="dispatch_plan",
        subject_id=SUBJECT,
        correlation_id="restart-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    await before.ainvoke(state, config)

    after = compile_graph(checkpointer, store)
    resumed = await after.ainvoke(
        Command(
            resume={
                "subject_id": SUBJECT,
                "decided_by": "dispatcher-1",
                "decided_at": datetime.now(UTC).isoformat(),
                "approved": False,
                "reason": "resource_unavailable",
            }
        ),
        config,
    )

    assert resumed["output"]["released"] is False
    assert store.rejected[0]["reason"] == "resource_unavailable"


def test_the_durable_checkpointer_is_what_a_real_restart_needs() -> None:
    """The in-process saver loses every paused run when the process dies.

    This test does not assert behaviour; it asserts that the distinction is visible in the
    code, so nobody reads the tests above as proof that a deployment with
    `SARANA_AGENT_DURABLE_CHECKPOINTS=false` would survive a restart. It would not.
    """
    from agent_svc.runtime.checkpoint import is_durable, memory_checkpointer

    assert not is_durable(memory_checkpointer())
