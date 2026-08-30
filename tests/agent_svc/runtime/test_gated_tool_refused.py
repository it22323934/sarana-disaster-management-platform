"""The runtime refuses to let an agent release money or commit a dispatch on its own.

Third of three independent layers over one property:

  1. the API gate — `Scope.DISBURSEMENT_RELEASE` and `Scope.DISPATCH_COMMIT` are refused to
     every machine principal, at the token;
  2. the database — `aid.disbursement` is append-only and `released_by` is NOT NULL;
  3. this — the tool registry refuses a gated tool without a verified human decision for
     that exact subject.

Three layers for one property looks like paranoia until you consider what it protects: an
agent, unattended, at 3 a.m., moving public money with nobody accountable. The whole
platform's credibility rests on that being impossible, and one layer is one bug away from
not being impossible.

Almost every test here is an attempt to get past it. A gate is worth what its narrowest
edge holds, and the narrow edge is not "no approval" — it is **an approval for something
else**. A state key copied between runs, a resume against the wrong thread, a supervisor
batching decisions: those produce a real, well-formed, genuinely-signed approval that is
about a different incident.
"""

from __future__ import annotations

import pytest

from agent_svc.runtime.errors import HumanGateMissing
from agent_svc.runtime.state import initial_state
from agent_svc.runtime.tools import ToolRegistry, ToolSpec, assert_human_gate

SUBJECT = "018f0000-0000-7000-8000-000000000001"
OTHER_SUBJECT = "018f0000-0000-7000-8000-000000000002"


def a_state(decision: dict[str, object] | None = None, subject: str = SUBJECT):
    state = initial_state(
        agent="dispatch",
        subject_type="incident",
        subject_id=subject,
        correlation_id="01a04200-0000-7000-8000-000000000000",
    )
    state["human_decision"] = decision
    return state


def an_approval(*, subject: str = SUBJECT, approved: bool = True) -> dict[str, object]:
    return {
        "subject_id": subject,
        "decided_by": "dispatcher@sarana.lk",
        "decided_at": "2026-08-30T04:00:00+00:00",
        "approved": approved,
    }


def a_registry() -> tuple[ToolRegistry, dict[str, int]]:
    """A registry with one gated tool and one open one, and a call counter."""
    registry = ToolRegistry()
    calls: dict[str, int] = {}

    async def release_dispatch(plan_id: str) -> str:
        calls["release"] = calls.get("release", 0) + 1
        return f"released:{plan_id}"

    async def read_division(code: str) -> str:
        calls["read"] = calls.get("read", 0) + 1
        return code

    registry.register(
        ToolSpec(
            name="release_dispatch",
            fn=release_dispatch,
            side_effect=True,
            requires_human_gate=True,
        )
    )
    registry.register(ToolSpec(name="read_division", fn=read_division, side_effect=False))
    return registry, calls


# --------------------------------------------------------------------------------------
# What the gate refuses
# --------------------------------------------------------------------------------------


async def test_a_gated_tool_with_no_decision_is_refused() -> None:
    """The obvious one. An agent reaching a gated tool without pausing is refused."""
    registry, calls = a_registry()

    with pytest.raises(HumanGateMissing, match="has none"):
        await registry.invoke("release_dispatch", a_state(), plan_id="p1")

    assert "release" not in calls, "the tool body must not have run"


async def test_an_approval_for_a_different_subject_is_refused() -> None:
    """The one this actually exists to catch.

    A real, well-formed, genuinely-signed approval — about a different incident. A copied
    state key, a resume on the wrong thread, a supervisor batching decisions. Checking a
    boolean would let every one of these through; comparing the ids is what makes an
    approval specific rather than ambient.
    """
    registry, calls = a_registry()
    state = a_state(an_approval(subject=OTHER_SUBJECT))

    with pytest.raises(HumanGateMissing, match="approves subject"):
        await registry.invoke("release_dispatch", state, plan_id="p1")

    assert "release" not in calls


async def test_a_refusal_is_not_an_absence() -> None:
    """A person said no. That is a decision, and it is not retried as though unanswered."""
    registry, calls = a_registry()
    state = a_state(an_approval(approved=False))

    with pytest.raises(HumanGateMissing, match="said no"):
        await registry.invoke("release_dispatch", state, plan_id="p1")

    assert "release" not in calls


@pytest.mark.parametrize("missing", ["subject_id", "decided_by", "decided_at", "approved"])
async def test_a_decision_missing_any_field_is_refused(missing: str) -> None:
    """A dict in the state that looks like a decision is not one.

    Each field is load-bearing: what was approved, by whom, when, and whether. A decision
    that does not name its approver cannot be audited, and one without a timestamp cannot
    be shown to have preceded the action.
    """
    registry, _ = a_registry()
    decision = an_approval()
    del decision[missing]

    with pytest.raises(HumanGateMissing, match="missing"):
        await registry.invoke("release_dispatch", a_state(decision), plan_id="p1")


async def test_an_empty_decision_is_refused() -> None:
    """An empty dict is falsy and must be treated as no decision, not as a permissive one."""
    registry, _ = a_registry()

    with pytest.raises(HumanGateMissing):
        await registry.invoke("release_dispatch", a_state({}), plan_id="p1")


# --------------------------------------------------------------------------------------
# What it allows
# --------------------------------------------------------------------------------------


async def test_a_matching_approval_lets_the_tool_run() -> None:
    """The gate is a gate, not a wall. A named person approving this subject opens it."""
    registry, calls = a_registry()

    result = await registry.invoke("release_dispatch", a_state(an_approval()), plan_id="p1")

    assert result == "released:p1"
    assert calls["release"] == 1


async def test_an_ungated_tool_needs_no_decision() -> None:
    """Reading the hierarchy is not a decision anybody has to make.

    Gating everything would train people to approve without reading, which is worse than
    gating nothing.
    """
    registry, calls = a_registry()

    assert await registry.invoke("read_division", a_state(), code="LK-21-01-001") == "LK-21-01-001"
    assert calls["read"] == 1


def test_the_gate_returns_the_decision_so_it_can_be_recorded() -> None:
    """Who approved what has to reach the audit entry, not just the control flow."""
    decision = assert_human_gate("release_dispatch", a_state(an_approval()))

    assert decision["decided_by"] == "dispatcher@sarana.lk"
    assert decision["subject_id"] == SUBJECT


# --------------------------------------------------------------------------------------
# The registry's own rules
# --------------------------------------------------------------------------------------


def test_a_gated_tool_must_be_marked_side_effecting() -> None:
    """A gate over something that changes nothing is a gate somebody removes as pointless.

    Refused at registration, where it is a five-second fix, rather than surviving as a
    contradiction somebody later resolves in the wrong direction.
    """
    with pytest.raises(ValueError, match="side_effect=True"):
        ToolSpec(
            name="pointless",
            fn=_noop,
            side_effect=False,
            requires_human_gate=True,
        )


def test_registering_two_tools_under_one_name_is_refused() -> None:
    """Otherwise the graph calls whichever was registered last, which nobody decided."""
    registry = ToolRegistry()
    registry.register(ToolSpec(name="dup", fn=_noop, side_effect=False))

    with pytest.raises(ValueError, match="registered twice"):
        registry.register(ToolSpec(name="dup", fn=_noop, side_effect=False))


def test_the_gated_tools_are_enumerable() -> None:
    """One place for a security review to read, rather than a grep across six agents."""
    registry, _ = a_registry()

    assert registry.gated() == ["release_dispatch"]
    assert registry.side_effecting() == ["release_dispatch"]


async def _noop() -> None:
    return None
