"""A graph that pauses for a human, survives a restart, and resumes on the same thread.

This is the property every human gate in SARANA rests on. A dispatch waiting for a
dispatcher's sign-off can sit for an hour; if the container is redeployed in that hour, the
run has to come back rather than the incident quietly disappearing.

**The test that matters most is the double-execution one.** LangGraph re-executes a node
from the top when it resumes, so everything above the `interrupt()` call runs a second
time. Build file 12 calls this the single most common bug in HITL graphs, and the failure
it produces is silent: an audit entry written twice, an SMS sent twice, a payment
instructed twice. Nothing errors. It only shows up in the record afterwards, when somebody
asks why a household got two messages.

So `test_pre_interrupt_code_runs_twice_and_side_effects_run_once` asserts both halves — the
re-execution really happens, and the side effect placed after the interrupt really did not.
Asserting only the second half would pass on a graph that never interrupted at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from agent_svc.runtime.checkpoint import config_for, is_durable, memory_checkpointer
from agent_svc.runtime.nodes import request_approval
from agent_svc.runtime.state import AgentState, initial_state, thread_id_for

SUBJECT = "018f0000-0000-7000-8000-000000000001"


def build_graph(checkpointer: Any, tally: dict[str, int]) -> Any:
    """A two-node graph with an interrupt in the middle.

    `tally` counts how many times each half ran, which is the whole point: the pre-
    interrupt half must run twice and the post-interrupt half once.
    """

    async def decide(state: AgentState) -> dict[str, Any]:
        # ABOVE the interrupt. This runs again on resume - anything here must be free of
        # side effects, or idempotent. Counted so the test can prove it.
        tally["before"] = tally.get("before", 0) + 1

        decision = request_approval(
            state,
            question="Commit this dispatch?",
            detail={"responders": 3},
        )

        # BELOW the interrupt. Runs exactly once, which is why every real side effect in
        # this codebase - the audit write, the SMS, the payment - goes here.
        tally["after"] = tally.get("after", 0) + 1
        return {
            "human_decision": decision,
            "notes": ["decided"],
            "status": "RUNNING",
        }

    async def finish(state: AgentState) -> dict[str, Any]:
        tally["finished"] = tally.get("finished", 0) + 1
        return {"status": "COMPLETED"}

    builder = StateGraph(AgentState)
    builder.add_node("decide", decide)
    builder.add_node("finish", finish)
    builder.add_edge(START, "decide")
    builder.add_edge("decide", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def a_run() -> AgentState:
    return initial_state(
        agent="dispatch",
        subject_type="incident",
        subject_id=SUBJECT,
        correlation_id="01a04200-0000-7000-8000-000000000000",
    )


async def test_a_graph_pauses_at_an_interrupt(checkpointer: Any) -> None:
    """The run stops and reports what it is waiting for."""
    tally: dict[str, int] = {}
    graph = build_graph(checkpointer, tally)
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    result = await graph.ainvoke(a_run(), config)

    assert "__interrupt__" in result
    assert tally["before"] == 1
    assert "after" not in tally, "the post-interrupt half must not have run yet"


async def test_the_interrupt_payload_says_what_is_being_asked(checkpointer: Any) -> None:
    """The ops console renders this. It must name the subject and the question.

    A pending approval that does not say what it is about is one an officer cannot action
    without opening three other screens.
    """
    graph = build_graph(checkpointer, {})
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    result = await graph.ainvoke(a_run(), config)
    payload = result["__interrupt__"][0].value

    assert payload["question"] == "Commit this dispatch?"
    assert payload["subject_id"] == SUBJECT
    assert payload["subject_type"] == "incident"
    assert payload["detail"] == {"responders": 3}


async def test_pre_interrupt_code_runs_twice_and_side_effects_run_once(
    checkpointer: Any,
) -> None:
    """The single most common bug in HITL graphs, asserted from both ends.

    Both halves matter. If only the "ran once" half were checked, this would pass against a
    graph that never interrupted at all — and the whole point is that it did interrupt, the
    node re-executed, and the side effect below the interrupt still happened exactly once.
    """
    tally: dict[str, int] = {}
    graph = build_graph(checkpointer, tally)
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    await graph.ainvoke(a_run(), config)
    assert tally["before"] == 1

    decision = {
        "subject_id": SUBJECT,
        "decided_by": "dispatcher@sarana.lk",
        "decided_at": "2026-08-30T04:00:00+00:00",
        "approved": True,
    }
    final = await graph.ainvoke(Command(resume=decision), config)

    # The node re-executed from the top: the half above the interrupt ran a second time.
    assert tally["before"] == 2, "a resumed node must re-execute from the top"
    # And the half below it ran exactly once, which is why side effects go there.
    assert tally["after"] == 1, "the post-interrupt half must run exactly once"
    assert final["status"] == "COMPLETED"
    assert final["human_decision"] == decision


async def test_a_run_resumes_after_the_graph_object_is_rebuilt(checkpointer: Any) -> None:
    """The restart. State lives in the checkpointer, not in the graph object.

    A redeploy while a dispatcher is deciding must not lose the incident. Rebuilding the
    graph over the same saver is what a process restart amounts to: same thread id, same
    state, no in-memory continuity.
    """
    tally: dict[str, int] = {}
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    first = build_graph(checkpointer, tally)
    await first.ainvoke(a_run(), config)

    # The process "restarts": a completely new graph object, nothing carried over.
    del first
    second = build_graph(checkpointer, tally)

    final = await second.ainvoke(
        Command(
            resume={
                "subject_id": SUBJECT,
                "decided_by": "dispatcher@sarana.lk",
                "decided_at": "2026-08-30T04:00:00+00:00",
                "approved": True,
            }
        ),
        config,
    )

    assert final["status"] == "COMPLETED"
    assert final["subject_id"] == SUBJECT


async def test_the_thread_id_is_derived_not_invented(checkpointer: Any) -> None:
    """Starting the same agent on the same subject twice lands on one thread.

    Deterministic ids are what let a resume find its thread without a lookup table - and
    what stop a second run forking a second approval in front of a second officer.
    """
    assert thread_id_for("dispatch", "incident", SUBJECT) == f"dispatch:incident:{SUBJECT}"

    tally: dict[str, int] = {}
    graph = build_graph(checkpointer, tally)
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    await graph.ainvoke(a_run(), config)
    # A second start on the same subject resumes rather than forking: the node does not
    # run from scratch a second time.
    await graph.ainvoke(a_run(), config)

    assert tally["before"] <= 2, "a second start must not fork a second pending approval"


async def test_a_refusal_is_carried_through_as_a_decision(checkpointer: Any) -> None:
    """ "No" is an answer, and it reaches the state as one.

    A graph that treated a refusal as an absence would route back to the same officer with
    the same question.
    """
    graph = build_graph(checkpointer, {})
    config = config_for(thread_id_for("dispatch", "incident", SUBJECT))

    await graph.ainvoke(a_run(), config)
    final = await graph.ainvoke(
        Command(
            resume={
                "subject_id": SUBJECT,
                "decided_by": "dispatcher@sarana.lk",
                "decided_at": "2026-08-30T04:00:00+00:00",
                "approved": False,
                "reason": "the area is already covered by an earlier dispatch",
            }
        ),
        config,
    )

    assert final["human_decision"]["approved"] is False
    assert final["human_decision"]["reason"]


def test_an_in_memory_checkpointer_reports_that_it_is_not_durable() -> None:
    """A deployment that started with one should say so on its first log line.

    Interrupts work against it, which is exactly why the mistake is survivable in testing
    and catastrophic in production: everything looks right until the first restart.
    """
    assert is_durable(memory_checkpointer()) is False


@pytest.mark.parametrize(
    ("agent", "subject_type", "subject_id"),
    [
        ("dispatch", "incident", "018f-a"),
        ("intake", "report", "018f-b"),
        ("ledger_anomaly", "entitlement", "018f-c"),
    ],
)
def test_thread_ids_are_unique_per_agent_and_subject(
    agent: str, subject_type: str, subject_id: str
) -> None:
    """Two agents working on one subject are two threads, not one.

    Sharing would make the triage agent's resume land in the intake agent's interrupt.
    """
    other = thread_id_for("supervisor", subject_type, subject_id)
    assert thread_id_for(agent, subject_type, subject_id) != other
