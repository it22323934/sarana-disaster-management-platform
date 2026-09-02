"""Assembling the plan a dispatcher approves, and the rationale they read.

## The interrupt payload is the approval screen's contract

Build file 16 puts it exactly that way, and it is the reason this module exists rather than
the graph building a dict inline. Everything a dispatcher needs in order to decide has to be
in `DispatchPlan.as_interrupt_payload()` — the incidents, the responders, the route, the
factor breakdown, the estimated duration, and **the unservable list**.

A gate where the person cannot see why is a rubber stamp, not a control. A dispatcher who
can only see what the plan proposes, and not what it could not reach, will approve it and
never know somebody was left out.

## The rationale is prose, and prose cannot move the queue

The model writes a short trilingual sentence explaining a ranking that has already been
computed. It reads the factors; it cannot change them. With the provider down the same
sentence comes from a template, the ranking is byte-identical, and the plan is identical in
every respect except the fluency of one paragraph.

That is why this agent is close to a non-event during a model outage, which is the property
build file 16 asks for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import structlog

from agent_svc.agents.triage.ports import Incident, ModelCall, Responder, RoutePlan
from agent_svc.agents.triage.scoring import TriageScore
from sarana_shared.domain.localised import REQUIRED_LOCALES

_log = structlog.get_logger(__name__)

# How many incidents one plan covers. A plan a dispatcher cannot read in a minute is one
# they approve without reading, which converts the gate into a formality. Twenty is about a
# screen.
MAX_INCIDENTS_PER_PLAN: Final = 20

# The trilingual template the rationale falls back to. Deliberately factual and dull: it
# states the driver, not a judgement, and it is what ships when there is no model.
_TEMPLATE: Final[dict[str, str]] = {
    "en": "{count} incidents ranked. Top: {top_type} in {top_division}, {top_reason}.",
    "si": "සිදුවීම් {count}ක් ශ්‍රේණිගත කර ඇත. ප්‍රමුඛ: {top_division} හි {top_type}, {top_reason}.",
    "ta": "{count} சம்பவங்கள் தரவரிசைப்படுத்தப்பட்டன. முதன்மை: {top_division} இல் {top_type}, {top_reason}.",
}

# The driver phrases, per language. Chosen from the heaviest contributing factor, so the
# sentence says the same thing the numbers do.
_DRIVERS: Final[dict[str, dict[str, str]]] = {
    "immediate_danger": {
        "en": "somebody is in immediate danger",
        "si": "යමෙකු ක්ෂණික අනතුරකට ලක්ව ඇත",
        "ta": "ஒருவர் உடனடி ஆபத்தில் உள்ளார்",
    },
    "people_at_risk": {
        "en": "the largest number of people at risk",
        "si": "වැඩිම පිරිසක් අවදානමේ",
        "ta": "அதிக மக்கள் ஆபத்தில்",
    },
    "vulnerability": {
        "en": "vulnerable people are present",
        "si": "අවදානම් සහගත පුද්ගලයින් සිටී",
        "ta": "பாதிக்கப்படக்கூடியவர்கள் உள்ளனர்",
    },
    "incident_type": {
        "en": "the incident type is the most time-critical",
        "si": "සිදුවීමේ වර්ගය වඩාත් හදිසි වේ",
        "ta": "சம்பவ வகை மிகவும் அவசரமானது",
    },
    "age": {
        "en": "it has been waiting longest",
        "si": "එය දීර්ඝතම කාලයක් රැඳී ඇත",
        "ta": "இது நீண்ட நேரமாக காத்திருக்கிறது",
    },
    "corroboration": {
        "en": "several independent reports confirm it",
        "si": "ස්වාධීන වාර්තා කිහිපයක් එය තහවුරු කරයි",
        "ta": "பல தனித்தனி அறிக்கைகள் இதை உறுதிப்படுத்துகின்றன",
    },
}


@dataclass(frozen=True, slots=True)
class DispatchPlan:
    """A proposed allocation, and everything the dispatcher needs to judge it."""

    plan_id: str
    incidents: list[Incident]
    responders: list[Responder]
    scores: list[TriageScore]
    routes: RoutePlan
    rationale: dict[str, str] = field(default_factory=dict)
    rationale_method: str = "TEMPLATE"
    proposed_at: datetime | None = None

    @property
    def incident_ids(self) -> list[str]:
        return [incident.incident_id for incident in self.incidents]

    @property
    def responder_ids(self) -> list[str]:
        return [responder.responder_id for responder in self.responders]

    @property
    def eta(self) -> int:
        return self.routes.estimated_duration_min

    def factor_breakdown(self) -> list[dict[str, Any]]:
        """Every incident's score with every term that produced it, in ranked order.

        The whole breakdown, not a summary. A dispatcher who disagrees with a ranking needs
        to be able to point at the term they disagree with — that is what makes this
        contestable rather than something to be over-trusted or ignored.
        """
        return [
            {
                "incident_id": score.incident_id,
                "rank": position + 1,
                "score": score.score,
                "dispatchability": score.dispatchability,
                "dispatchable": score.dispatchable,
                "model_version": score.model_version,
                "method": score.method,
                "factors": score.factors,
                "explanation": score.explanation(),
            }
            for position, score in enumerate(self.scores)
        ]

    def as_interrupt_payload(self) -> dict[str, Any]:
        """The approval screen's contract.

        Build file 16 names each of these fields. `unservable` is in it because a plan that
        showed only what it proposed would let a dispatcher approve while somebody they
        never saw was left unreached.
        """
        return {
            "kind": "dispatch_signoff",
            "plan_id": self.plan_id,
            "incidents": [incident.summary() for incident in self.incidents],
            "responders": [responder.summary() for responder in self.responders],
            "route_summary": self.routes.route_summary(),
            "unservable": [item.as_dict() for item in self.routes.unservable],
            "factors": self.factor_breakdown(),
            "estimated_duration_min": self.eta,
            "routing_method": self.routes.method,
            "routing_status": self.routes.solver_status,
            "rationale": self.rationale,
            "rationale_method": self.rationale_method,
        }

    def as_route_column(self) -> dict[str, Any]:
        """What goes in `incident.dispatch_plan.route`, a JSONB column."""
        return {
            "routes": self.routes.route_summary(),
            "unservable": [item.as_dict() for item in self.routes.unservable],
            "method": self.routes.method,
            "status": self.routes.solver_status,
            "factors": self.factor_breakdown(),
            "rationale": self.rationale,
            "rationale_method": self.rationale_method,
        }


def top_driver(score: TriageScore) -> str:
    """Which factor contributed most to this incident's rank.

    Read off the contributions rather than asserted, so the sentence and the numbers cannot
    drift apart — if the heaviest term changes, the prose changes with it.
    """
    contributions = score.factors.get("contributions", {})
    if not contributions:
        return "incident_type"
    return str(max(contributions, key=lambda name: contributions[name]))


def template_rationale(scores: list[TriageScore], incidents: dict[str, Incident]) -> dict[str, str]:
    """The trilingual sentence, rendered from the factors with no model at all.

    All three languages, because it is shown in an operations room where the officer on
    duty may read any of them, and the platform's rule is that nothing citizen-adjacent
    exists in fewer than three.
    """
    if not scores:
        return {
            locale.value: {
                "en": "No incidents to rank.",
                "si": "ශ්‍රේණිගත කිරීමට සිදුවීම් නොමැත.",
                "ta": "தரவரிசைப்படுத்த சம்பவங்கள் இல்லை.",
            }[locale.value]
            for locale in REQUIRED_LOCALES
        }

    top = scores[0]
    incident = incidents.get(top.incident_id)
    driver = top_driver(top)

    return {
        locale.value: _TEMPLATE[locale.value].format(
            count=len(scores),
            top_type=incident.incident_type if incident else "incident",
            top_division=incident.gn_division_code if incident else "?",
            top_reason=_DRIVERS.get(driver, _DRIVERS["incident_type"])[locale.value],
        )
        for locale in REQUIRED_LOCALES
    }


async def write_rationale(
    scores: list[TriageScore],
    incidents: dict[str, Incident],
    *,
    call: ModelCall | None = None,
) -> tuple[dict[str, str], str]:
    """The rationale and how it was produced.

    Returns the template version whenever a model is absent, unreachable, or returns
    something that is not three languages. The ranking is unaffected either way — this is
    the only place a model appears in this agent, and it is downstream of every decision.
    """
    fallback = template_rationale(scores, incidents)
    if call is None or not scores:
        return fallback, "TEMPLATE"

    try:
        answer = await call(_rationale_prompt(scores, incidents))
    except Exception as error:  # noqa: BLE001 - a dispatch plan does not wait on prose
        _log.warning(
            "triage_rationale_model_unavailable",
            error=type(error).__name__,
            impact="the template rationale was used; the ranking and the routes are identical",
        )
        return fallback, "TEMPLATE"

    parsed = _parse_rationale(answer)
    if parsed is None:
        _log.warning(
            "triage_rationale_unusable",
            impact="the model did not return all three languages; the template was used",
        )
        return fallback, "TEMPLATE"

    return parsed, "LLM"


def _rationale_prompt(scores: list[TriageScore], incidents: dict[str, Incident]) -> str:
    """The prompt. Facts in, one sentence per language out.

    The model is given the computed ranking and told to explain it. It is not asked what the
    ranking should be, and there is no path by which its answer could change one — the
    scores are already fixed by the time this is called.
    """
    top = scores[0]
    incident = incidents.get(top.incident_id)
    lines = [
        "You are writing one short sentence for a Sri Lankan dispatcher, in three "
        "languages, explaining an already-computed incident ranking.",
        "",
        'Return only JSON: {"si": "...", "ta": "...", "en": "..."}',
        "",
        "Do not re-rank anything. Do not add facts. Do not name a person or a household.",
        "One sentence per language, under 200 characters each.",
        "",
        f"Incidents ranked: {len(scores)}",
        f"Highest priority: {incident.incident_type if incident else '?'} in "
        f"{incident.gn_division_code if incident else '?'}",
        f"Its score: {top.score:.3f}",
        f"Heaviest factor: {top_driver(top)}",
        "",
        "JSON:",
    ]
    return "\n".join(lines)


def _parse_rationale(answer: str) -> dict[str, str] | None:
    """Three languages or nothing.

    A rationale missing Tamil is not a rationale that gets shown with Tamil blank - it is
    one that gets replaced by the template, which has all three. Partial output is the one
    thing this platform never renders.
    """
    import json

    body = answer.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()

    try:
        raw = json.loads(body)
    except (ValueError, TypeError):
        return None

    if not isinstance(raw, dict):
        return None

    parsed = {locale.value: str(raw.get(locale.value, "")).strip() for locale in REQUIRED_LOCALES}
    if not all(parsed.values()):
        return None
    return parsed


def assemble(
    *,
    plan_id: str,
    scores: list[TriageScore],
    incidents: dict[str, Incident],
    responders: list[Responder],
    routes: RoutePlan,
    rationale: dict[str, str],
    rationale_method: str,
    proposed_at: datetime | None = None,
) -> DispatchPlan:
    """Build the plan from the parts, in ranked order.

    Only the incidents the routes actually serve go in `incidents`. The ones that could not
    be served are in `routes.unservable`, where the approval screen renders them separately -
    a dispatcher needs to see the difference between "we are sending someone" and "we cannot
    reach this", and putting them in one list would hide it.
    """
    served = set(routes.served)
    ordered = [
        incidents[score.incident_id]
        for score in scores
        if score.incident_id in served and score.incident_id in incidents
    ]
    return DispatchPlan(
        plan_id=plan_id,
        incidents=ordered,
        responders=responders,
        scores=scores,
        routes=routes,
        rationale=rationale,
        rationale_method=rationale_method,
        proposed_at=proposed_at,
    )
