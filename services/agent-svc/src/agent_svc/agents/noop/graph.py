r"""The reference graph: classify, maybe ask a human, record.

Read this before writing a real agent. It is the shape files 13-18 follow, and the order of
the nodes is the safety design rather than an implementation detail.

```
START -> classify -> (confident?) -> record -> END
                  \-> approve -> record -> END
```

Four things it demonstrates, each of which a real agent needs:

**The deterministic path is the only path here.** `classify` reaches no model. A real agent
calls one and falls back to logic like this when the provider is unreachable, over budget,
or too slow — and labels the output `provenance="DETERMINISTIC"` so nobody downstream
mistakes a rule for a judgement.

**Low confidence routes to a person, not onward.** `with_confidence` is what turns
`AgentOutput.confidence` from a number in a payload into a gate.

**The interrupt is placed so the side effect is after it.** The node re-executes from the
top on resume; `record` is a separate node downstream precisely so it cannot run twice.

**Every node that changes anything writes an audit entry.** Non-negotiable #4. Here that is
`record`, and it is the last node for the same reason.
"""

from __future__ import annotations

from typing import Any, Final

import structlog
from langgraph.graph import END, START, StateGraph

from agent_svc.runtime.nodes import audit_write, request_approval, with_confidence
from agent_svc.runtime.registry import AgentSpec
from agent_svc.runtime.state import AgentOutput, AgentState

_log = structlog.get_logger(__name__)

AGENT: Final = "noop"

# Above this the graph proceeds on its own; below it, a person decides. The same value the
# rest of the runtime reviews at, so one agent is not quietly more permissive than another.
CONFIDENCE_THRESHOLD: Final = 0.70

# Words that make the deterministic classifier sure. Crude and deliberately so: this is the
# fallback, and a fallback nobody can read the rules of is one nobody trusts under pressure.
CONFIDENT_MARKERS: Final[frozenset[str]] = frozenset({"flood", "landslide", "collapse"})


class NoopOutput(AgentOutput):
    """What this agent concludes. A real agent's output model is its own."""

    category: str


async def classify(state: AgentState) -> dict[str, Any]:
    """Decide a category, without a model.

    A real agent calls one here and falls back to something like this when the provider is
    unreachable. The output is labelled `DETERMINISTIC` either way it was produced, because
    a rule presented as a judgement is a lie about how the decision was made — and the
    person reading it decides differently depending on which it was.
    """
    text = str(state.get("output", {}).get("text", "")).lower()
    matched = sorted(marker for marker in CONFIDENT_MARKERS if marker in text)

    if matched:
        output = NoopOutput(
            category=matched[0],
            confidence=0.95,
            reasoning=f"the report names {matched[0]} explicitly",
            needs_human_review=False,
            provenance="DETERMINISTIC",
        )
    else:
        output = NoopOutput(
            category="unknown",
            confidence=0.30,
            reasoning="no recognised hazard word in the report",
            needs_human_review=True,
            review_reason="the deterministic classifier could not place this report",
            provenance="DETERMINISTIC",
        )

    return {"output": output.model_dump(mode="json"), "notes": [f"classified: {output.category}"]}


async def approve(state: AgentState) -> dict[str, Any]:
    """Pause for a person when the classifier was not sure.

    **This node re-executes from the top when the run resumes.** Everything above the
    `interrupt()` runs a second time, so nothing above it may have a side effect that is
    not idempotent. There is deliberately nothing above it here but reading state.
    """
    output = dict(state.get("output", {}))

    decision = request_approval(
        state,
        question="The classifier was not confident. What is this report about?",
        detail={
            "suggested": output.get("category"),
            "confidence": output.get("confidence"),
            "why": output.get("review_reason"),
        },
    )

    # Below the interrupt. Runs exactly once.
    return {
        "human_decision": decision,
        "output": {
            **output,
            "category": decision.get("category", output.get("category")),
            # A human's answer is the answer. Overwriting the provenance is the point:
            # downstream must not treat this as something the classifier concluded.
            "provenance": "HUMAN",
            "needs_human_review": False,
        },
        "notes": ["human decided the category"],
    }


async def record(state: AgentState) -> dict[str, Any]:
    """Write the audit entry and finish.

    A separate node from `approve` on purpose: it is downstream of the interrupt, so it
    runs once however many times the approving node re-executed.
    """
    audited = await audit_write(
        state,
        action="noop.classified",
        subject=str(state.get("subject_id", "")),
        detail={
            "category": state.get("output", {}).get("category"),
            "provenance": state.get("output", {}).get("provenance"),
        },
        writer=None,
    )
    return {**audited, "status": "COMPLETED"}


def _needs_human(state: AgentState) -> str:
    """Where to go after classifying."""
    return "approve" if state.get("output", {}).get("needs_human_review") else "record"


def build(checkpointer: Any) -> Any:
    """Compile the graph. Called once per process at boot."""
    builder = StateGraph(AgentState)

    builder.add_node("classify", with_confidence(classify, threshold=CONFIDENCE_THRESHOLD))
    builder.add_node("approve", approve)
    builder.add_node("record", record)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify", _needs_human, {"approve": "approve", "record": "record"}
    )
    builder.add_edge("approve", "record")
    builder.add_edge("record", END)

    return builder.compile(checkpointer=checkpointer)


SPEC: Final = AgentSpec(
    name=AGENT,
    subject_type="report",
    build=build,
    description="The reference agent. Classifies a report deterministically and asks a "
    "person when it cannot.",
    degraded_note="It is already the degraded path: no model is called at all, so a "
    "provider outage changes nothing about how it behaves.",
    gated=False,
)
