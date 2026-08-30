"""Reconciling sources that disagree, and the one rule the model cannot break.

The Department of Meteorology issues Yellow / Amber / Red against **districts**. NBRO issues
WATCH / WARNING / EVACUATE against **DS divisions** inside them. They are different scales
measuring different hazards on different geometries, issued by different institutions at
different hours, and during a cyclone they routinely disagree about the same place.

Somebody has to decide what that place's hazard level is. That decision is this module.

## The invariant

**The reconciled level is never less severe than the most severe source.** Not a preference,
not a prompt instruction, not something the model is asked to respect - a hard floor applied
to whatever comes back, after it comes back.

The reason is asymmetric consequence. Over-warning a division costs an unnecessary
preposition and some credibility. Under-warning one costs the thing the platform exists to
prevent. A model that talks itself out of NBRO's EVACUATE because the Met bulletin only says
Amber has produced a defensible-sounding paragraph and a fatal answer, and no amount of
prompt engineering makes that risk acceptable when a single `max()` removes it entirely.

So the model's job is narrower than it looks: it explains *why* the sources differ and how
much to trust the reconciliation. It cannot lower the level, and it cannot invent one - the
output is constrained to the levels actually observed, and anything else is discarded.

## What the degraded path does

Exactly what the floor does: take the most severe source, and say so. That is why the
degraded path is not a worry here. Losing the model costs the *explanation*, never the
decision, because the decision was never the model's to make.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import structlog

_log = structlog.get_logger(__name__)

# One ordinal scale across two institutions' vocabularies, so "more severe" is a comparison
# and not an argument. The alignment is a judgement and it is written down here rather than
# implied by dictionary order:
#
#   Met Yellow  ~ NBRO WATCH     - be aware, conditions are developing
#   Met Amber   ~ NBRO WARNING   - act now, damage is expected
#   Met Red     ~ NBRO EVACUATE  - move people
#
# NBRO's scale is the one tied to a published rainfall threshold, so where the two land on
# the same rung the NBRO reading is the one an officer can check against a gauge.
SEVERITY: Final[dict[str, int]] = {
    "NONE": 0,
    "YELLOW": 1,
    "WATCH": 1,
    "AMBER": 2,
    "WARNING": 2,
    "RED": 3,
    "EVACUATE": 3,
}

# What the reconciled level is expressed in. NBRO's vocabulary, because it is the one with
# a number behind it: an officer can ask "how many millimetres is WARNING here?" and get an
# answer, which is not true of Amber.
CANONICAL: Final[tuple[str, ...]] = ("NONE", "WATCH", "WARNING", "EVACUATE")

# How specific a claim is. A bulletin issued against one DS division says more about that
# division than a district-wide warning does, and where severity ties the specific one is
# the better description. It can never *lower* the level - see the invariant above.
SPECIFICITY: Final[dict[str, int]] = {"national": 0, "district": 1, "ds_division": 2}


@dataclass(frozen=True, slots=True)
class SourceClaim:
    """One institution's statement about one place."""

    source: str
    level: str
    scope_type: str
    scope_code: str
    issued_at: datetime | None = None
    headline: str = ""

    @property
    def severity(self) -> int:
        return SEVERITY.get(self.level.upper(), 0)

    @property
    def specificity(self) -> int:
        return SPECIFICITY.get(self.scope_type, 0)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What the platform decided the hazard level is, and how it got there."""

    level: str
    severity: int
    chosen_source: str
    rationale: str
    confidence: float

    # `CONSERVATIVE` is the deterministic path: most severe wins, no model involved.
    # `LLM` means a model wrote the rationale and its choice survived the floor. Recorded
    # because a reconciliation nobody can attribute is one nobody can review.
    method: str

    @property
    def used_a_model(self) -> bool:
        return self.method == "LLM"


def most_severe(claims: list[SourceClaim]) -> SourceClaim | None:
    """The claim that wins on the deterministic path.

    Ties break on specificity, then on recency: two sources at the same severity, and the
    one describing a smaller area more recently is the better description of it.
    """
    if not claims:
        return None
    return max(
        claims,
        key=lambda claim: (
            claim.severity,
            claim.specificity,
            claim.issued_at.timestamp() if claim.issued_at else 0.0,
        ),
    )


def sources_disagree(claims: list[SourceClaim]) -> bool:
    """Whether reconciling is even a question.

    The model is not called when every source says the same thing. Most hours of most
    events, they do - and a token spent agreeing with an agreement is a token spent to
    reach the answer the floor would have given for free.
    """
    return len({claim.severity for claim in claims}) > 1


def conservative(claims: list[SourceClaim]) -> Reconciliation:
    """The deterministic reconciliation. Also the floor, and also the degraded path.

    One function for all three so they cannot drift apart: a degraded path that differs
    from the floor is a platform that behaves differently depending on whether OpenAI is
    up, in the one decision where that must never be true.
    """
    winner = most_severe(claims)
    if winner is None:
        return Reconciliation(
            level="NONE",
            severity=0,
            chosen_source="none",
            rationale="No source issued anything for this area.",
            confidence=0.5,
            method="CONSERVATIVE",
        )

    others = [claim for claim in claims if claim is not winner]
    if others:
        rationale = (
            f"{winner.source} reports {winner.level} for {winner.scope_code}; "
            + "; ".join(f"{claim.source} reports {claim.level}" for claim in others)
            + ". Taking the most severe."
        )
    else:
        rationale = f"{winner.source} reports {winner.level} for {winner.scope_code}."

    return Reconciliation(
        level=canonical_level(winner.severity),
        severity=winner.severity,
        chosen_source=winner.source,
        rationale=rationale,
        # Agreement is worth more than a resolved disagreement. Sources that concur have
        # independently reached the same reading; a conflict resolved by taking the worse
        # one is a decision made under uncertainty, and the number should say so.
        confidence=0.6 if sources_disagree(claims) else 0.9,
        method="CONSERVATIVE",
    )


def canonical_level(severity: int) -> str:
    """The NBRO-vocabulary level for a severity rung."""
    return CANONICAL[max(0, min(len(CANONICAL) - 1, severity))]


PROMPT: Final = """You are reconciling two Sri Lankan government hazard bulletins that \
disagree about the same area.

Sources:
{claims}

Answer with JSON only, no prose around it:
{{"level": one of {allowed}, "rationale": "one or two sentences", "confidence": 0.0-1.0}}

Rules you must follow:
- `level` must be one of the levels listed above. Do not invent a level.
- Explain which source is more specific to this area and why that matters.
- Do not introduce any number that does not appear in the sources.
- Write for a district officer deciding whether to preposition, not for a meteorologist."""


def build_prompt(claims: list[SourceClaim]) -> str:
    """The prompt, built here so a test can read exactly what the model is asked."""
    described = "\n".join(
        f"- {claim.source} says {claim.level} for {claim.scope_type} {claim.scope_code}"
        + (f" ({claim.headline})" if claim.headline else "")
        for claim in claims
    )
    allowed = sorted({claim.level.upper() for claim in claims} | {"NONE"})
    return PROMPT.format(claims=described, allowed=allowed)


def apply_floor(candidate: Reconciliation, claims: list[SourceClaim]) -> Reconciliation:
    """Enforce the invariant on whatever the model returned.

    Applied after the call rather than asked for in the prompt, because a rule that only
    exists in a prompt is a rule the model may decline to follow on the one input that
    matters. If the model's answer is below the floor it is replaced entirely - the
    rationale goes with it, since a rationale for a level that was overruled is worse than
    no rationale at all.
    """
    floor = conservative(claims)
    if candidate.severity >= floor.severity:
        return candidate

    _log.warning(
        "forecast_reconciliation_below_floor",
        model_level=candidate.level,
        floor_level=floor.level,
        impact="the model proposed a less severe level than a source reported; the "
        "source's level stands and the model's rationale is discarded",
    )
    return floor


def parse_response(raw: str, claims: list[SourceClaim]) -> Reconciliation | None:
    """Turn a model response into a reconciliation, or None if it is not usable.

    None rather than an exception: an unusable response is an ordinary event on the
    degraded path, and the caller already knows what to do about it.

    Two things are rejected. **A level not among those observed** - the model has invented a
    hazard level, which is the specific failure build file 13 warns about. **Anything that
    does not parse** - including the fenced code block a model returns about a third of the
    time, which is stripped before parsing rather than being treated as a failure.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        _log.warning("forecast_reconciliation_unparseable", response=raw[:200])
        return None

    if not isinstance(data, dict):
        return None

    level = str(data.get("level", "")).upper()
    observed = {claim.level.upper() for claim in claims} | {"NONE"}
    if level not in observed:
        _log.warning(
            "forecast_reconciliation_invented_level",
            level=level,
            observed=sorted(observed),
            impact="the model returned a hazard level no source reported; falling back to "
            "the most severe source",
        )
        return None

    rationale = str(data.get("rationale", "")).strip()
    if not rationale:
        return None

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    return Reconciliation(
        level=canonical_level(SEVERITY.get(level, 0)),
        severity=SEVERITY.get(level, 0),
        chosen_source="reconciled",
        rationale=rationale,
        confidence=max(0.0, min(1.0, confidence)),
        method="LLM",
    )


async def reconcile(
    claims: list[SourceClaim],
    *,
    call: Any = None,
) -> Reconciliation:
    """Decide one area's hazard level.

    `call` is an async callable taking the prompt and returning the model's text. None -
    which is every test and every deployment without an API key - takes the deterministic
    path, and so does any failure inside the call. The result is identical in severity
    either way; only the rationale differs.
    """
    if not sources_disagree(claims) or call is None:
        return conservative(claims)

    try:
        raw = await call(build_prompt(claims))
    except Exception as error:  # noqa: BLE001 - a provider outage degrades, it does not fail
        _log.warning(
            "forecast_reconciliation_degraded",
            error=type(error).__name__,
            impact="reconciliation fell back to the most severe source; the hazard level "
            "is unchanged and only the written rationale is lost",
        )
        return conservative(claims)

    parsed = parse_response(str(raw), claims)
    if parsed is None:
        return conservative(claims)

    return apply_floor(parsed, claims)
