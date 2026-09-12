"""Five threads interrupted, a restart, and all five resume correctly.

Build file 18 names this file. The property is what makes an indefinite gate affordable: a
dispatcher does not have to answer inside a request timeout, before a deploy, or at all, and
a redeploy in the middle of a cyclone does not lose the queue of decisions waiting.

## What this proves, and what it cannot

Each phase compiles a **new graph object** over a shared checkpointer, which is what stands
in for the restart. That proves the half this repository owns: thread ids are derivable, the
checkpoint carries everything a resume needs, and nothing lives in the compiled graph or the
closures around it.

It does **not** prove that Postgres round-trips a checkpoint — that needs
`AsyncPostgresSaver` and a container restart. `tests/agent_svc/runtime/test_interrupt_resume.py`
covers the saver, and `HANDOFF.md` records that the two halves have never been run end to end
against a restarted container.

Saying so plainly matters more than a green tick would: the property is real and the proof is
partial.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langgraph.types import Command

from agent_svc.agents.supervisor import graph as supervisor
from agent_svc.runtime.checkpoint import config_for, is_durable, memory_checkpointer
from agent_svc.runtime.state import initial_state, thread_id_for
from tests.agents.supervisor.conftest import APPROVER, NOW, FakeApprovals, approval

READY = {"intake_verified", "intake_deduplicated", "triaged"}
SUBJECTS = [f"plan-{index}" for index in range(1, 6)]


def compile_graph(checkpointer, approvals: FakeApprovals):
    """A fresh graph object over a shared checkpointer. The stand-in for the restart."""
    return supervisor.build(checkpointer, approvals=approvals, now=NOW)


async def pause_one(graph, subject: str) -> dict:
    state = initial_state(
        agent="supervisor",
        subject_type="event",
        subject_id=subject,
        correlation_id=f"c-{subject}",
    )
    state["output"] = {
        "event_type": "sarana.dispatch.signoff.requested",
        "subject_id": subject,
        "gate": "dispatch_signoff",
        "payload": {},
    }
    config = config_for(thread_id_for("supervisor", "event", subject))
    return await graph.ainvoke(state, config)


def resume_for(subject: str) -> Command:
    return Command(
        resume={
            "subject_id": subject,
            "decided_by": APPROVER,
            "decided_at": datetime.now(UTC).isoformat(),
            "approved": True,
        }
    )


async def test_five_interrupted_threads_all_resume_after_a_restart() -> None:
    """The headline case from build file 18."""
    checkpointer = memory_checkpointer()
    approvals = FakeApprovals(
        records={
            ("dispatch_signoff", subject): approval(subject_id=subject) for subject in SUBJECTS
        },
        facts={subject: set(READY) for subject in SUBJECTS},
    )

    before = compile_graph(checkpointer, approvals)
    for subject in SUBJECTS:
        paused = await pause_one(before, subject)
        assert paused["__interrupt__"], f"{subject} did not pause"

    # The restart. A new graph object sharing nothing but the checkpointer.
    after = compile_graph(checkpointer, approvals)

    for subject in SUBJECTS:
        resumed = await after.ainvoke(
            resume_for(subject), config_for(thread_id_for("supervisor", "event", subject))
        )
        assert resumed["status"] == "COMPLETED", f"{subject} did not complete"
        assert resumed["output"]["committed"] is True, f"{subject} did not commit"


async def test_each_thread_resumes_onto_its_own_subject() -> None:
    """The failure this catches: five threads that all resume, onto the wrong subjects.

    A count of five completions proves nothing on its own - the ids have to match.
    """
    checkpointer = memory_checkpointer()
    approvals = FakeApprovals(
        records={
            ("dispatch_signoff", subject): approval(subject_id=subject) for subject in SUBJECTS
        },
        facts={subject: set(READY) for subject in SUBJECTS},
    )

    before = compile_graph(checkpointer, approvals)
    for subject in SUBJECTS:
        await pause_one(before, subject)

    after = compile_graph(checkpointer, approvals)
    committed = []
    for subject in SUBJECTS:
        resumed = await after.ainvoke(
            resume_for(subject), config_for(thread_id_for("supervisor", "event", subject))
        )
        committed.append(resumed["output"]["subject_id"])

    assert committed == SUBJECTS


async def test_a_paused_thread_still_carries_its_gate_payload_after_the_restart() -> None:
    """A dispatcher opening the inbox after a redeploy sees the same screen.

    If the payload were rebuilt from the closures rather than read from the checkpoint it
    would be empty here, because the graph is a new object.
    """
    checkpointer = memory_checkpointer()
    approvals = FakeApprovals(
        records={("dispatch_signoff", "plan-1"): approval()},
        facts={"plan-1": set(READY)},
    )

    before = compile_graph(checkpointer, approvals)
    await pause_one(before, "plan-1")

    after = compile_graph(checkpointer, approvals)
    snapshot = await after.aget_state(config_for(thread_id_for("supervisor", "event", "plan-1")))

    assert snapshot.next, "the thread is still paused"
    assert snapshot.values["gate"] == "dispatch_signoff"
    assert snapshot.values["subject_id"] == "plan-1"


async def test_resuming_one_thread_leaves_the_others_paused() -> None:
    """A resume is addressed to a thread, not to the process."""
    checkpointer = memory_checkpointer()
    approvals = FakeApprovals(
        records={
            ("dispatch_signoff", subject): approval(subject_id=subject) for subject in SUBJECTS
        },
        facts={subject: set(READY) for subject in SUBJECTS},
    )

    graph = compile_graph(checkpointer, approvals)
    for subject in SUBJECTS:
        await pause_one(graph, subject)

    await graph.ainvoke(
        resume_for("plan-1"), config_for(thread_id_for("supervisor", "event", "plan-1"))
    )

    for subject in SUBJECTS[1:]:
        snapshot = await graph.aget_state(config_for(thread_id_for("supervisor", "event", subject)))
        assert snapshot.next, f"{subject} should still be paused"


def test_the_thread_id_is_derivable_from_the_subject() -> None:
    """A restarted process reconstructs the thread from the row, without searching."""
    assert thread_id_for("supervisor", "event", "plan-1") == "supervisor:event:plan-1"


def test_the_in_process_saver_is_not_durable_and_the_code_says_so() -> None:
    """This test asserts no behaviour. It exists so nobody reads the tests above as proof
    that a deployment with `SARANA_AGENT_DURABLE_CHECKPOINTS=false` survives a restart. It
    would lose every paused gate."""
    assert not is_durable(memory_checkpointer())
