"""The warning agent, in the shape the evaluation harness can score.

```bash
make eval AGENT=warning
python -m agent_svc.runtime.eval --agent warning --fixtures data/fixtures/smoke
```

## What this measures, and what it does not

The production graph talks to alerting-svc, core-api and a telco gateway. A harness that
had to stand all three up before it could report a number is a harness nobody runs before
pushing, so what is evaluated is the part of this agent that has **a decision with a
confidence worth calibrating**: which template a forecast selects, and whether that
selection should go to a person.

That is the honest boundary, and it is drawn where it is because of what the other parts
are. Targeting is a database query. The quiet-hours rule and the fatigue window are
comparisons against a clock. The gap report is arithmetic over receipts. None of them
produces a probability, all of them are guarded by their own tests, and scoring them here
would produce a calibration curve for a lookup table.

## What "accuracy" means here

The label on each case is the template code the catalogue should produce for that hazard
and impact class, or `null` for a case where nothing fits and a person must decide. Those
labels are read off NBRO's escalation points and the published catalogue rather than off
this code, so a change that makes class 4 flood select a warning instead of an evacuation
order fails the eval. That makes this a regression gate on the selection rules, which is
what it is for - and calling it skill at choosing warnings would be the same overclaim the
whole agent is built to avoid.

The `no_suitable_template` cases are in the set on purpose. Without them the low-confidence
bin is empty, and a calibration number computed over cases the agent is certain about says
nothing at all.
"""

from __future__ import annotations

from typing import Any, Final

from langgraph.graph import END, START, StateGraph

from agent_svc.agents.warning import catalogue as templates
from agent_svc.agents.warning import channels as channel_rules
from agent_svc.agents.warning.ports import AlertTemplate
from agent_svc.runtime.state import AgentState

# The catalogue a case is scored against when it does not carry its own. The twelve seeded
# templates, as PUBLISHED - which in a real deployment they are not until a named Sinhala
# reviewer and a named Tamil reviewer have each signed. Reduced to the fields selection
# reads: the eval is scoring which code comes out, not what the Tamil body says.
EVAL_CATALOGUE: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("FLOOD_WATCH", "FLOOD", "MODERATE", "{gn_division_name}"),
    ("FLOOD_WARNING", "FLOOD", "SEVERE", "{gn_division_name}"),
    ("FLOOD_EVACUATE_IMMEDIATE", "FLOOD", "EXTREME", "{gn_division_name} {shelter_name}"),
    ("LANDSLIDE_WATCH", "LANDSLIDE", "MODERATE", "{gn_division_name}"),
    ("LANDSLIDE_WARNING", "LANDSLIDE", "SEVERE", "{gn_division_name} {shelter_name}"),
    ("CYCLONE_WARNING", "CYCLONE", "EXTREME", "{gn_division_name} {deadline_time}"),
    ("STORM_SURGE_WARNING", "STORM_SURGE", "EXTREME", "{gn_division_name} {shelter_name}"),
)


def catalogue_from(raw: list[dict[str, Any]] | None) -> list[AlertTemplate]:
    """The published catalogue for one case.

    A case supplying its own is testing selection against a catalogue with a gap in it,
    which is a real state: a template is only published once two named native speakers have
    signed it, and a deployment mid-review has fewer than twelve.
    """
    rows = raw or [
        {"code": code, "hazard_type": hazard, "severity": severity, "body": body}
        for code, hazard, severity, body in EVAL_CATALOGUE
    ]
    return [
        AlertTemplate(
            id=f"eval-{row['code']}",
            code=str(row["code"]),
            hazard_type=str(row["hazard_type"]),
            severity=str(row["severity"]),
            urgency=str(row.get("urgency", "IMMEDIATE")),
            certainty=str(row.get("certainty", "LIKELY")),
            body={
                "si": str(row.get("body", "")),
                "ta": str(row.get("body", "")),
                "en": str(row.get("body", "")),
            },
        )
        for row in rows
    ]


def facts_from(raw: dict[str, Any]) -> templates.SelectionFacts:
    """One case's structured facts.

    A case that omits `shelter_name` is testing what happens when the template that fits
    cannot be filled - which is the case that must produce a review item rather than a
    quietly less severe alert.
    """
    return templates.SelectionFacts(
        gn_division_name=str(raw.get("gn_division_name", "Gampola")),
        shelter_name=raw.get("shelter_name"),
        deadline_time=raw.get("deadline_time", "18:00"),
        effective_time=raw.get("effective_time", "12:00"),
        district_name=raw.get("district_name"),
        road_name=raw.get("road_name"),
        distribution_point=raw.get("distribution_point"),
        hazard_name=raw.get("hazard_name", "Flood"),
    )


async def select_one(state: AgentState) -> dict[str, Any]:
    """Select a template for the single forecast a case describes.

    The output keys are what the fixtures label against: `template_code` is the answer
    (`none` when a person has to decide), `confidence` is what gets calibrated, and
    `provenance` says a rule produced it.
    """
    raw = dict(state.get("output", {}))
    hazard = str(raw.get("hazard_type", "FLOOD")).upper()
    impact_class = int(raw.get("impact_class", 0))

    if impact_class < channel_rules.ALERT_FROM:
        return _answer(
            code="none",
            confidence=0.95,
            reasoning=(
                f"impact class {impact_class} is below the alerting threshold; no public "
                "alert is issued"
            ),
            needs_human_review=False,
        )

    try:
        choice = await templates.select(
            hazard_type=hazard,
            impact_class=impact_class,
            catalogue=catalogue_from(raw.get("catalogue")),
            facts=facts_from(raw),
            call=None,
        )
    except templates.NoSuitableTemplate as error:
        return _answer(
            code="none",
            # Low, and it should be: this is the agent saying it cannot answer, and the
            # calibration curve needs the cases where that is true.
            confidence=0.2,
            reasoning=str(error),
            needs_human_review=True,
            review_reason=f"no_suitable_template: {error}",
        )

    return _answer(
        code=choice.template.code,
        confidence=choice.confidence,
        reasoning=choice.reasoning,
        needs_human_review=False,
    )


def _answer(
    *,
    code: str,
    confidence: float,
    reasoning: str,
    needs_human_review: bool,
    review_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "COMPLETED",
        "output": {
            "template_code": code,
            "confidence": confidence,
            "reasoning": reasoning,
            "needs_human_review": needs_human_review,
            "review_reason": review_reason,
            # Always. A rule presented as a judgement is a lie about how the decision was
            # made, and the eval report is one of the places somebody checks.
            "provenance": "DETERMINISTIC",
        },
        "notes": [f"selected {code}"],
    }


def build(checkpointer: Any) -> Any:
    """A one-node graph over template selection.

    Deliberately not the production graph. See the module docstring for why, and for what
    that means the resulting numbers do and do not say.
    """
    builder = StateGraph(AgentState)
    builder.add_node("select", select_one)
    builder.add_edge(START, "select")
    builder.add_edge("select", END)
    return builder.compile(checkpointer=checkpointer)
