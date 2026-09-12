"""The intake agent, in the shape the evaluation harness can score.

```bash
make eval AGENT=intake
python -m agent_svc.runtime.eval --agent intake --fixtures data/fixtures/smoke
```

## What this measures

Extraction: the incident type a report yields, and whether the agent asked for a person.
That is the decision with a confidence worth calibrating, and it is the one every later
stage depends on - a report typed as SUPPLIES_NEEDED when somebody is trapped is ranked
below a request for milk powder.

## What it does not measure, and why that is stated rather than quietly omitted

Build file 15 asks the eval to report per-language WER, dedup precision and recall, and the
false-merge rate. Three of those cannot honestly be produced yet and the fourth is measured
elsewhere:

**Per-language WER needs a held-out set of real Sinhala and Tamil audio with human
transcripts.** No such set exists in this repository, and there is no way to invent one -
generating audio to measure ASR against would measure the generator. The build file is right
that a blended WER number hiding a bad Tamil result is worse than none, and the same logic
applies here: a WER printed from fixtures nobody recorded would be exactly that number. It
stays absent, and `HANDOFF.md` says so.

**Dedup precision, recall and the false-merge rate** are measured by
`tests/agents/intake/test_dedup.py` against labelled pairs, which is where they belong: they
are properties of a pairwise decision, not of a single report, and the harness scores one
case at a time. `dedup.DedupStats` computes both rates together for the day a labelled
corpus exists.

Reporting an accuracy figure for the parts that can be measured, and saying plainly what is
not measured, is the honest version. A report with a WER column full of fabricated numbers
would be read by somebody who does not know they were fabricated.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.intake import extraction
from agent_svc.runtime.state import AgentState


async def extract_one(state: AgentState) -> dict[str, Any]:
    """Extract from the single report a case describes.

    Runs the deterministic path unless a case supplies text a model would be needed for -
    which none do, because a fixture whose answer depends on a provider being reachable is
    a fixture that fails in CI on a bad afternoon.

    The output keys are what the fixtures label against: `incident_type` is the answer,
    `needs_human_review` is whether it asked for a person, and `confidence` is what gets
    calibrated.
    """
    raw = dict(state.get("output", {}))
    text = str(raw.get("text", ""))

    result = await extraction.extract(text, call=None)

    # A case may supply an unverifiable count to exercise the basis post-check - the single
    # most important refusal in this agent, and one that would otherwise never appear in
    # the eval because the keyword path never produces a count at all.
    if raw.get("claimed_people_at_risk") is not None:
        claimed = result.model_copy(
            update={
                "people_at_risk": int(raw["claimed_people_at_risk"]),
                "people_at_risk_basis": str(raw.get("claimed_basis", "")),
            }
        )
        result = extraction.enforce_basis(claimed, source=text)

    return {
        "status": "COMPLETED",
        "output": {
            "incident_type": result.incident_type,
            "people_at_risk": result.people_at_risk,
            "immediate_danger": result.immediate_danger,
            "vulnerable_present": sorted(result.vulnerable_present),
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "needs_human_review": result.needs_human_review,
            "review_reason": result.review_reason,
            # Always. A keyword match presented as a judgement is a lie about how the
            # decision was made, and the eval report is one of the places somebody checks.
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"extracted {result.incident_type}"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over extraction.

    Deliberately not the production graph. See the module docstring for what that means the
    resulting numbers do and do not say.
    """
    builder = StateGraph(AgentState)
    builder.add_node("extract", extract_one)
    builder.add_edge(START, "extract")
    builder.add_edge("extract", END)
    return builder.compile(checkpointer=checkpointer)
