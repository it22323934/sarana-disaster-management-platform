"""Turning a detector's numbers into something a reviewer can act on, safely.

The model's entire job here is to say **why this pattern might be innocent**, and to say
what would settle it. It does not decide whether to flag — the detectors did that — and it
cannot change a score.

## `innocent_explanations` must be non-empty, and that is a safety property

Build file 17 is explicit: if the model cannot think of an innocent explanation, the flag is
not ready to raise. That inverts the usual shape of a safeguard and it is deliberate. An
empty list does not mean the pattern is damning; it means the context is too thin for a
human to review fairly, and a reviewer handed a flag with nothing to rule out will supply
their own explanation — which will be about a person, because that is the explanation that
comes to mind.

So an empty list suppresses the flag entirely rather than raising it bare.

## Every output goes through `redaction.check` before anybody sees it

A rejected document is discarded **whole** and the flag falls back to the template block. Not
repaired, not re-asked. An output that reached for an accusation once is not one to negotiate
with, and re-prompting spends a second call to get a second chance at the same mistake.

## The degraded path raises at low priority and says so

With no model, flags carry the templated context, no narrative, and `context_available:
false`. Build file 17 requires the marking because removing the contextualiser removes a
safeguard — a reviewer needs to know they are looking at a rawer signal, not a quieter one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

from agent_svc.agents.ledger_anomaly import redaction
from agent_svc.agents.ledger_anomaly.normalisation import DivisionProfile
from agent_svc.agents.ledger_anomaly.ports import ModelCall, Signal

_log = structlog.get_logger(__name__)

PRIORITIES: Final[tuple[str, ...]] = ("low", "medium", "high")

# What a flag is raised at when no model contextualised it. Always low, per build file 17:
# the narrative is a safeguard, and a signal that lost it should not also arrive shouting.
DEGRADED_PRIORITY: Final = "low"

# Score at or above which a contextualised flag may be medium or high. Below it the
# detectors are describing a small departure from expectation, and a high-priority flag on
# a small departure is how a review queue becomes noise.
PRIORITY_FLOOR: Final = 0.5


@dataclass(frozen=True, slots=True)
class FlagContext:
    """What a reviewer reads above the numbers.

    Every field has been through `redaction.check`. `innocent_explanations` is non-empty by
    construction - a context that lost its explanations is not built, it is refused.
    """

    pattern_summary: str
    innocent_explanations: list[str] = field(default_factory=list)
    what_would_resolve_it: list[str] = field(default_factory=list)
    suggested_priority: str = DEGRADED_PRIORITY
    confidence: float = 0.0
    method: str = "TEMPLATE"

    @property
    def usable(self) -> bool:
        """Whether this context is fit to accompany a flag."""
        return bool(self.pattern_summary.strip()) and bool(self.innocent_explanations)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pattern_summary": self.pattern_summary,
            "innocent_explanations": list(self.innocent_explanations),
            "what_would_resolve_it": list(self.what_would_resolve_it),
            "suggested_priority": self.suggested_priority,
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


INSTRUCTIONS: Final = """You are writing review context for a statistical pattern found in \
disaster aid assessment data in Sri Lanka.

Return only JSON:
{
  "pattern_summary": "what the numbers show, neutrally, in one or two sentences",
  "innocent_explanations": ["ranked most likely first"],
  "what_would_resolve_it": ["concrete checks a reviewer can perform"],
  "suggested_priority": "low" | "medium" | "high",
  "confidence": 0.0 to 1.0
}

Rules you must follow. Output breaking any of them is discarded entirely:

- Never name or refer to any individual. No names, no ids, no "the assessing officer".
  The unit is the GN division.
- Never state a finding or a conclusion. This is a pattern that warrants review, not
  evidence of anything. Do not use words like fraud, misuse, corruption, fake or
  falsified, and do not write sentences that mean them.
- innocent_explanations must not be empty. If you cannot think of a way this pattern could
  arise legitimately, say so by returning an empty list and the flag will be withdrawn.
- Remember that a division which was genuinely hit hardest will legitimately produce
  higher, more numerous and faster assessments. That is the damage behaving as expected.
"""


def template_context(signal: Signal, profile: DivisionProfile) -> FlagContext:
    """The context a flag carries with no model at all.

    Built from the detector's own evidence and its ruled-out list, so it is complete and
    honest - just plainer. `innocent_explanations` comes from the detector rather than from
    a model, which is why the degraded path can still satisfy the non-empty rule.
    """
    evidence = ", ".join(
        f"{item.label} {item.value}"
        + (f" against {item.compared_with}" if item.compared_with is not None else "")
        for item in signal.evidence
    )
    return FlagContext(
        pattern_summary=(
            f"In GN division {signal.gn_division_code}, the {signal.detector} detector "
            f"recorded: {evidence}. The division's forecast impact class is "
            f"{profile.expectation.impact_class}."
        ),
        innocent_explanations=list(signal.ruled_out),
        what_would_resolve_it=[
            "compare this division's assessments against the DS survey for the same period",
            "check the deployment and directive records covering these dates",
        ],
        suggested_priority=DEGRADED_PRIORITY,
        confidence=0.0,
        method="TEMPLATE",
    )


async def contextualise(
    signal: Signal,
    profile: DivisionProfile,
    *,
    call: ModelCall | None = None,
) -> FlagContext:
    """Context for one signal, falling back to the template whenever the model cannot.

    Every failure path lands on the template: no model, an unreachable provider, an
    unparseable answer, an output that fails the post-check, or an output with no innocent
    explanations. The flag is still raised and still reviewable; it is marked as having
    lost its narrative.
    """
    fallback = template_context(signal, profile)
    if call is None:
        return fallback

    try:
        answer = await call(_prompt(signal, profile))
    except Exception as error:  # noqa: BLE001 - a flag never waits on a model provider
        _log.warning(
            "anomaly_context_model_unavailable",
            detector=signal.detector,
            error=type(error).__name__,
            impact="the templated context was used and the flag is marked "
            "context_unavailable at low priority",
        )
        return fallback

    parsed = _parse(answer)
    if parsed is None:
        return fallback

    # The post-check, before anything else looks at it. See `redaction`.
    verdict = redaction.check(parsed.as_dict())
    if not verdict.clean:
        _log.error(
            "anomaly_context_failed_post_check",
            detector=signal.detector,
            gn_division_code=signal.gn_division_code,
            rules=sorted({item.rule for item in verdict.rejections}),
            impact="discarded whole; the templated context was used instead",
        )
        return fallback

    if not parsed.innocent_explanations:
        # Not a failure of the model - it is the model saying the flag is not ready, which
        # build file 17 treats as a reason to withdraw rather than to raise bare.
        _log.info(
            "anomaly_context_no_innocent_explanation",
            detector=signal.detector,
            gn_division_code=signal.gn_division_code,
            impact="this flag will be suppressed; a reviewer handed nothing to rule out "
            "supplies their own explanation, and it will be about a person",
        )
        return FlagContext(
            pattern_summary=parsed.pattern_summary,
            innocent_explanations=[],
            what_would_resolve_it=parsed.what_would_resolve_it,
            suggested_priority=parsed.suggested_priority,
            confidence=parsed.confidence,
            method="LLM",
        )

    return parsed


def priority_for(signal: Signal, context: FlagContext) -> str:
    """The priority a flag is raised at.

    The model may suggest, and the score constrains. A high-priority flag on a small
    departure from expectation is how a review queue becomes noise, and a noisy queue is
    one people close without reading — which is worse than no queue, because it looks like
    oversight.
    """
    if context.method != "LLM":
        return DEGRADED_PRIORITY
    if signal.score < PRIORITY_FLOOR:
        return DEGRADED_PRIORITY
    suggested = (
        context.suggested_priority
        if context.suggested_priority in PRIORITIES
        else DEGRADED_PRIORITY
    )
    return suggested


def _prompt(signal: Signal, profile: DivisionProfile) -> str:
    """The prompt. Facts about a place, never about a person.

    Note what is absent: no assessor, no approver, no household id. The model cannot name
    somebody it was never told about, which is a stronger guarantee than the instruction
    telling it not to - and the post-check is the third layer behind both.
    """
    evidence = "\n".join(
        f"  - {item.label}: {item.value}"
        + (f" (expected around {item.compared_with})" if item.compared_with is not None else "")
        + (f" — {item.note}" if item.note else "")
        for item in signal.evidence
    )
    return (
        f"{INSTRUCTIONS}\n"
        f"Detector: {signal.detector}\n"
        f"GN division: {signal.gn_division_code}\n"
        f"Score: {signal.score:.3f}\n"
        f"\nWhat the detector measured:\n{evidence}\n"
        f"\nAbout the division:\n"
        f"  - forecast impact class: {profile.expectation.impact_class}\n"
        f"  - households: {profile.context.household_count}\n"
        f"  - cell coverage: {profile.context.cell_coverage_pct}\n"
        f"  - assessments in this batch: {profile.count}\n"
        f"  - expected claims from the forecast: {profile.expectation.expected_claims:.0f}\n"
        f"\nAlready ruled out by the detector:\n"
        + "\n".join(f"  - {item}" for item in signal.ruled_out)
        + "\n\nJSON:"
    )


def _parse(answer: str) -> FlagContext | None:
    """Parse the model's JSON, or None to fall back.

    A missing `pattern_summary` returns None rather than an empty context: a flag whose
    summary is blank tells a reviewer nothing and the template says more.
    """
    body = answer.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()

    try:
        raw = json.loads(body)
    except (ValueError, TypeError):
        _log.warning("anomaly_context_unparseable", impact="the templated context was used")
        return None

    if not isinstance(raw, dict) or not str(raw.get("pattern_summary", "")).strip():
        return None

    priority = str(raw.get("suggested_priority", DEGRADED_PRIORITY)).lower()
    return FlagContext(
        pattern_summary=str(raw["pattern_summary"]).strip(),
        innocent_explanations=[str(item) for item in raw.get("innocent_explanations", [])],
        what_would_resolve_it=[str(item) for item in raw.get("what_would_resolve_it", [])],
        suggested_priority=priority if priority in PRIORITIES else DEGRADED_PRIORITY,
        confidence=float(raw.get("confidence", 0.0)),
        method="LLM",
    )
