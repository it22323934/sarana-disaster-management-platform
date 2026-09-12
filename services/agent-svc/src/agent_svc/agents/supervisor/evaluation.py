"""The supervisor, in the shape the evaluation harness can score.

```bash
make eval AGENT=supervisor
```

## What is scored, and why it is routing rather than judgement

The supervisor makes no judgements. Routing is a table, the gates are database reads, and
the one model call proposes a conflict resolution for a human. So what an eval can measure
is whether the **table fires correctly** - which agents an event starts, and which it
refuses for a sequencing violation.

That is a regression gate on the routing rules, and it is the right thing to gate on: the
dangerous failure in this agent is not a wrong answer, it is a route that fires early. An
incident reaching triage before intake verified it is a crew dispatched on an unverified
report, and nothing downstream would catch it.

## What is not scored here

The gates. Their properties are not metrics - they are refusals, and
`test_gates_three_layers.py` asserts each of the three layers independently by disabling the
other two. An accuracy figure over a safety property would be a number that could be 99% and
still mean the gate is broken.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.supervisor import routes
from agent_svc.runtime.state import AgentState


async def route_one_event(state: AgentState) -> dict[str, Any]:
    """Route the single event a case describes.

    The output keys are what the fixtures label against: `started` names the agents, and
    `refused` names the ones held back by a sequencing constraint.
    """
    raw = dict(state.get("output", {}))
    routing = routes.route(
        str(raw.get("event_type", "")),
        dict(raw.get("payload", {})),
        known_facts=set(raw.get("known_facts", [])),
    )

    started = sorted(trigger.agent for trigger in routing.fired)
    refused = sorted(trigger.agent for trigger, _ in routing.refused)

    return {
        "status": "COMPLETED",
        "output": {
            "started": started,
            "refused": refused,
            "violated": bool(refused),
            # The table is deterministic and has no belief about itself. Stating anything
            # other than certainty would be inventing a number to fill a field.
            "confidence": 1.0,
            "reasoning": (
                f"started {', '.join(started) or 'nothing'}"
                + (f"; refused {', '.join(refused)} on sequencing" if refused else "")
            ),
            "needs_human_review": False,
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"{len(started)} started, {len(refused)} refused"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over the routing table."""
    builder = StateGraph(AgentState)
    builder.add_node("route", route_one_event)
    builder.add_edge(START, "route")
    builder.add_edge("route", END)
    return builder.compile(checkpointer=checkpointer)
