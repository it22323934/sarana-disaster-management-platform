"""The triage agent, in the shape the evaluation harness can score.

```bash
make eval AGENT=triage
```

## Rank correlation, not binary agreement

Build file 16 sets a target of ≥85% agreement between the agent's ranking and human
judgement, and is explicit that it must be measured as **rank correlation on the same
incident set**, not as agree/disagree. The distinction matters: a dispatcher who works the
queue in a slightly different order has not disagreed with it, and scoring that as a failure
would push the formula towards whichever ordering happened to be in the fixtures.

`spearman()` below is the measure, and `rank_agreement()` maps it onto [0, 1] so the harness
- which scores one case at a time against a label - can gate on it.

Each eval case is a **whole queue** with a dispatcher's ordering attached. The agent ranks
it, the correlation is computed, and the case passes when the correlation clears the target.
That is a different shape from the other agents' evals, and it is the right one here: a
ranking is a property of a set, and scoring incidents individually would measure something
nobody uses.

## What the disagreements are for

The report names the pairs the agent ordered differently from the dispatcher. Build file 16
asks for that specifically, and it is the part worth reading: the aggregate number says
whether the formula is broadly right, and the inversions say *where* it is wrong in a way
that matters.

## What this does not measure

The routes. OR-Tools' output is deterministic given the same inputs and is checked by
`tests/agents/triage/test_routing.py` against known geometry; scoring it here would compare
a solver against itself. The gate is likewise a property, not a metric —
`test_gate_cannot_be_bypassed.py` asserts it at four independent layers.
"""

from __future__ import annotations

from typing import Any, Final

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.triage import scoring
from agent_svc.runtime.state import AgentState

# The target from the proposal, as a correlation rather than an accuracy.
TARGET_AGREEMENT: Final = 0.85


def spearman(left: list[str], right: list[str]) -> float:
    """Spearman rank correlation between two orderings of the same items.

    Returns 1.0 for identical orderings, -1.0 for exact reversals, 0.0 for unrelated ones.

    Items missing from either list are ignored rather than treated as ties: a dispatcher's
    working order recorded from a real shift will not always cover every incident that was
    open, and inventing a rank for the ones they did not reach would measure the invention.

    Fewer than two shared items returns 1.0 - there is no ordering to disagree about, and
    reporting 0.0 would drag the aggregate down with cases that said nothing.
    """
    shared = [item for item in left if item in set(right)]
    if len(shared) < 2:
        return 1.0

    left_rank = {item: position for position, item in enumerate(left)}
    right_rank = {item: position for position, item in enumerate(right)}

    # Ranked within the shared subset, so removing an item the dispatcher never reached
    # does not shift every rank below it.
    ordered_left = sorted(shared, key=lambda item: left_rank[item])
    ordered_right = sorted(shared, key=lambda item: right_rank[item])
    positions_left = {item: index for index, item in enumerate(ordered_left)}
    positions_right = {item: index for index, item in enumerate(ordered_right)}

    n = len(shared)
    d_squared = sum((positions_left[item] - positions_right[item]) ** 2 for item in shared)
    return 1.0 - (6.0 * d_squared) / (n * (n * n - 1))


def rank_agreement(left: list[str], right: list[str]) -> float:
    """Spearman mapped onto [0, 1], which is what the target is expressed in.

    A correlation of 1.0 is full agreement and -1.0 is a complete reversal, so the midpoint
    of the mapped scale is "unrelated". The 0.85 target therefore means genuinely close
    agreement, not "better than a coin toss".
    """
    return (spearman(left, right) + 1.0) / 2.0


def inversions(agent_order: list[str], human_order: list[str]) -> list[tuple[str, str]]:
    """Every pair the agent and the dispatcher ordered differently.

    The part of the report worth reading. The aggregate says whether the formula is broadly
    right; these say where it is wrong, and each one is a case somebody can look at.
    """
    shared = [item for item in agent_order if item in set(human_order)]
    human_rank = {item: position for position, item in enumerate(human_order)}

    found: list[tuple[str, str]] = []
    for i, first in enumerate(shared):
        for second in shared[i + 1 :]:
            if human_rank[first] > human_rank[second]:
                found.append((first, second))
    return found


def factors_from(raw: dict[str, Any]) -> scoring.TriageFactors:
    """One incident from a fixture case."""
    return scoring.TriageFactors(
        incident_id=str(raw["incident_id"]),
        incident_type=str(raw.get("incident_type", "OTHER")),
        immediate_danger=bool(raw.get("immediate_danger", False)),
        people_at_risk=raw.get("people_at_risk"),
        vulnerable_present=tuple(raw.get("vulnerable_present", [])),
        minutes_since_report=float(raw.get("minutes_since_report", 0.0)),
        location_confidence=float(raw.get("location_confidence", 1.0)),
        access_feasibility=float(raw.get("access_feasibility", 1.0)),
        corroboration_count=int(raw.get("corroboration_count", 1)),
    )


async def rank_one_queue(state: AgentState) -> dict[str, Any]:
    """Rank the queue a case describes and compare it with the dispatcher's order.

    The output keys are what the fixtures label against: `meets_target` is the answer,
    `agreement` is the measured correlation, and the inversions are carried so the report
    can name them.
    """
    raw = dict(state.get("output", {}))
    queue = [factors_from(item) for item in raw.get("incidents", [])]
    human_order = [str(item) for item in raw.get("dispatcher_order", [])]

    ranked = scoring.rank(queue)
    agent_order = [score.incident_id for score in ranked]

    agreement = rank_agreement(agent_order, human_order) if human_order else 1.0
    disagreements = inversions(agent_order, human_order) if human_order else []

    return {
        "status": "COMPLETED",
        "output": {
            "meets_target": agreement >= TARGET_AGREEMENT,
            "agreement": round(agreement, 4),
            "agent_order": agent_order,
            "inversions": [list(pair) for pair in disagreements],
            # The formula is deterministic, so its confidence in its own ordering is the
            # measured agreement rather than a separate belief. Stating anything else would
            # be inventing a number to fill a field.
            "confidence": round(agreement, 4),
            "reasoning": (
                f"ranked {len(agent_order)} incidents; rank agreement with the dispatcher "
                f"{agreement:.1%}"
                + (f", {len(disagreements)} pair(s) ordered differently" if disagreements else "")
            ),
            "needs_human_review": False,
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"rank agreement {agreement:.1%}"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over the ranking.

    Deliberately not the production graph: that one writes a plan and pauses on a human,
    and an eval that paused on every case would measure the fixtures' patience.
    """
    builder = StateGraph(AgentState)
    builder.add_node("rank", rank_one_queue)
    builder.add_edge(START, "rank")
    builder.add_edge("rank", END)
    return builder.compile(checkpointer=checkpointer)
