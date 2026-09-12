"""Deciding whether two reports are the same emergency, biased toward saying no.

## The two costs are not symmetric, and everything here follows from that

A **duplicate incident** costs a dispatcher ten seconds. They see two entries for one
collapsed house, merge them, and move on.

A **false merge** costs somebody their rescue. A household reports, their report is folded
into another family's incident, one team is sent to that address, and the family who
reported waits for someone who is never coming. Nobody notices, because from the outside the
system looks like it is working - there is an incident, it has a team, the queue is short.

So this module under-merges on purpose. Build file 15 sets a target of under 3% duplicates
and says the target must never be pursued by merging aggressively, and the way that promise
is kept is structural rather than aspirational:

- the auto-link threshold is high;
- the ambiguous band goes to a model, and the model's answer is only acted on when it is
  confident **and** says yes;
- an unsure model produces **two incidents and a flagged pair**, not one incident;
- a model that is unavailable produces two incidents and a flagged pair;
- a model that returns nonsense produces two incidents and a flagged pair.

Every failure mode lands on "separate, and tell a person". That is the design.

## Reporting a duplicate rate without a false-merge rate is misleading

`DedupStats` carries both, and the eval report prints both. A duplicate rate on its own can
always be improved by merging harder, which is the exact behaviour that must not be
rewarded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import structlog

from agent_svc.agents.intake.ports import ModelCall, NeighbourReport

_log = structlog.get_logger(__name__)

# Cosine similarity at or above which two reports are the same event without asking.
# High: at 0.90 the texts are saying substantially the same thing about the same place in
# the same ten minutes, and the remaining risk is small enough to trade for the latency.
AUTO_LINK_SIMILARITY: Final = 0.90

# Below this, two reports are different events and nothing further is spent on them.
SEPARATE_SIMILARITY: Final = 0.72

# How many candidates the recall stage pulls back. Twenty is generous for one division in a
# ninety-minute window and cheap: the cost of the kNN is the same whether it returns two or
# twenty, and a candidate that is never retrieved can never be matched.
CANDIDATE_LIMIT: Final = 20

# The window duplicates are searched within. Ninety minutes covers a household reporting
# again while they wait, and a neighbour reporting the same collapse an hour later; beyond
# it, a second report about the same address is usually a genuinely new development.
WINDOW_MINUTES: Final = 90

# How sure the adjudicating model must be before a merge happens on its word alone.
# Deliberately above the platform's ordinary 0.70 review threshold: this is the one
# decision in the agent whose wrong answer is invisible afterwards.
MERGE_CONFIDENCE: Final = 0.85

METHOD_VECTOR: Final = "pgvector-cosine-v1"
METHOD_ADJUDICATED: Final = "llm-adjudicated-v1"


@dataclass(frozen=True, slots=True)
class Verdict:
    """What was decided about one candidate pair, and why.

    `flag_for_human` is set on every uncertain outcome, and it is the field the review queue
    reads. A verdict of "separate" with no flag means the pair was confidently different; a
    verdict of "separate" with a flag means nobody could tell, and two incidents exist that
    might be one.
    """

    neighbour: NeighbourReport
    same_incident: bool
    confidence: float
    method: str
    reasoning: str
    flag_for_human: bool = False

    @property
    def links(self) -> bool:
        """Whether this verdict actually attaches the report to the neighbour's incident."""
        return self.same_incident and self.neighbour.incident_id is not None


@dataclass(frozen=True, slots=True)
class DedupDecision:
    """What happened to one incoming report across all its candidates."""

    link_to_incident: str | None = None
    verdicts: list[Verdict] = field(default_factory=list)
    considered: int = 0

    @property
    def flagged_pairs(self) -> list[str]:
        """Report ids a person should look at alongside this one."""
        return [verdict.neighbour.report_id for verdict in self.verdicts if verdict.flag_for_human]

    @property
    def merged(self) -> bool:
        return self.link_to_incident is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "link_to_incident": self.link_to_incident,
            "flagged_pairs": self.flagged_pairs,
            "verdicts": [
                {
                    "report_id": verdict.neighbour.report_id,
                    "similarity": round(verdict.neighbour.similarity, 4),
                    "same_incident": verdict.same_incident,
                    "confidence": round(verdict.confidence, 3),
                    "method": verdict.method,
                    "reasoning": verdict.reasoning,
                    "flagged": verdict.flag_for_human,
                }
                for verdict in self.verdicts
            ],
        }


@dataclass(frozen=True, slots=True)
class DedupStats:
    """Both rates, always together.

    A duplicate rate reported alone is a number that improves whenever the system merges
    harder, which is the behaviour that must not be rewarded. The eval prints these as a
    pair for that reason.
    """

    pairs: int
    linked: int
    false_merges: int
    missed_duplicates: int

    @property
    def duplicate_rate(self) -> float:
        """Share of truly-duplicate pairs that were left separate."""
        return self.missed_duplicates / self.pairs if self.pairs else 0.0

    @property
    def false_merge_rate(self) -> float:
        """Share of truly-different pairs that were merged. The one that costs somebody."""
        return self.false_merges / self.pairs if self.pairs else 0.0

    def as_sentence(self) -> str:
        return (
            f"{self.linked} of {self.pairs} pairs linked; "
            f"{self.missed_duplicates} duplicates missed ({self.duplicate_rate:.1%}), "
            f"{self.false_merges} false merges ({self.false_merge_rate:.1%})"
        )


def window_start(now: datetime, *, minutes: int = WINDOW_MINUTES) -> datetime:
    """The earliest a candidate could have been received and still be the same event."""
    return now - timedelta(minutes=minutes)


def band_of(similarity: float) -> str:
    """Which of the three bands a similarity falls in."""
    if similarity >= AUTO_LINK_SIMILARITY:
        return "auto_link"
    if similarity < SEPARATE_SIMILARITY:
        return "separate"
    return "ambiguous"


async def adjudicate(
    incoming_text: str,
    incoming_original: str,
    neighbour: NeighbourReport,
    *,
    occurred_at: datetime,
    call: ModelCall | None,
) -> Verdict:
    """Decide one ambiguous pair.

    Every path that is not "the model was confident and said yes" produces a verdict of
    *separate* with a flag. That includes an unavailable provider, an unparseable answer,
    a low-confidence yes, and a confident no - because the only outcome that merges two
    households' reports should be one somebody can point at afterwards.
    """
    if call is None:
        return Verdict(
            neighbour=neighbour,
            same_incident=False,
            confidence=neighbour.similarity,
            method=METHOD_VECTOR,
            reasoning=(
                "no model was available to adjudicate; the pair is in the ambiguous band "
                "and has been left as two incidents for a person to compare"
            ),
            flag_for_human=True,
        )

    try:
        answer = await call(
            _prompt(incoming_text, incoming_original, neighbour, occurred_at=occurred_at)
        )
        parsed = _parse(answer)
    except Exception as error:  # noqa: BLE001 - every failure lands on "separate, and flag"
        _log.warning(
            "intake_dedup_adjudication_failed",
            error=type(error).__name__,
            neighbour=neighbour.report_id,
            impact="the pair was left as two incidents and flagged for a person",
        )
        return Verdict(
            neighbour=neighbour,
            same_incident=False,
            confidence=neighbour.similarity,
            method=METHOD_VECTOR,
            reasoning=f"adjudication failed ({type(error).__name__}); left separate and flagged",
            flag_for_human=True,
        )

    same, confidence, reasoning = parsed
    if same and confidence >= MERGE_CONFIDENCE:
        return Verdict(
            neighbour=neighbour,
            same_incident=True,
            confidence=confidence,
            method=METHOD_ADJUDICATED,
            reasoning=reasoning,
        )

    return Verdict(
        neighbour=neighbour,
        same_incident=False,
        confidence=confidence,
        method=METHOD_ADJUDICATED,
        reasoning=reasoning
        or (
            "the adjudicator was not confident enough to merge two households' reports; "
            "left separate and flagged"
        ),
        # Flagged whenever the model leaned towards "same" without reaching the bar. A
        # confident "different" is a real answer and does not need a person.
        flag_for_human=same or confidence < MERGE_CONFIDENCE,
    )


async def decide(
    *,
    incoming_text: str,
    incoming_original: str,
    occurred_at: datetime,
    neighbours: list[NeighbourReport],
    call: ModelCall | None = None,
) -> DedupDecision:
    """Work through the candidates and decide what this report attaches to.

    Candidates are considered most similar first and the first link wins. A report is one
    event; attaching it to two incidents would be a merge of those two incidents by the back
    door, decided by nobody.
    """
    verdicts: list[Verdict] = []
    link: str | None = None

    for neighbour in sorted(neighbours, key=lambda candidate: -candidate.similarity):
        band = band_of(neighbour.similarity)

        if band == "separate":
            continue

        if band == "auto_link":
            verdict = Verdict(
                neighbour=neighbour,
                same_incident=True,
                confidence=neighbour.similarity,
                method=METHOD_VECTOR,
                reasoning=(
                    f"cosine similarity {neighbour.similarity:.3f} is at or above the "
                    f"{AUTO_LINK_SIMILARITY} auto-link threshold, in the same division "
                    "and window"
                ),
            )
        else:
            verdict = await adjudicate(
                incoming_text,
                incoming_original,
                neighbour,
                occurred_at=occurred_at,
                call=call,
            )

        verdicts.append(verdict)
        if link is None and verdict.links:
            link = verdict.neighbour.incident_id

    if link:
        _log.info(
            "intake_report_linked",
            incident_id=link,
            considered=len(neighbours),
            method=next(v.method for v in verdicts if v.links),
        )
    elif any(verdict.flag_for_human for verdict in verdicts):
        _log.info(
            "intake_duplicate_pair_flagged",
            pairs=[verdict.neighbour.report_id for verdict in verdicts if verdict.flag_for_human],
            impact="two incidents exist that may be one; a person compares them",
        )

    return DedupDecision(link_to_incident=link, verdicts=verdicts, considered=len(neighbours))


ADJUDICATION_INSTRUCTIONS: Final = """You are deciding whether two emergency reports from \
Sri Lanka describe the SAME real-world incident or two different ones.

Answer only with JSON: {"same_incident": true|false, "confidence": 0.0-1.0, "reasoning": \
"one sentence"}

This decision is asymmetric and you must treat it that way. Saying two different \
emergencies are the same means one household's report is folded into another's, one team \
is sent, and the family who reported waits for help that never comes. Saying two reports \
of one emergency are different costs a dispatcher ten seconds.

So: only answer true when the reports describe the same event at the same place. Different \
households, different buildings, or different times are different incidents even when the \
wording is similar. When you are unsure, answer false.

The reports may be in different languages. Two people describing one collapsed house in \
Sinhala and Tamil is the same incident.
"""


def _prompt(
    incoming_text: str,
    incoming_original: str,
    neighbour: NeighbourReport,
    *,
    occurred_at: datetime,
) -> str:
    """Both reports, in both their languages, with times and places.

    The original-language text is included alongside the English for both sides. A
    translation loses the detail that distinguishes two neighbouring households - a street
    name, a nickname for a landmark - and that detail is exactly what this decision turns
    on.
    """
    minutes = abs((neighbour.occurred_at - occurred_at).total_seconds()) / 60.0
    return (
        f"{ADJUDICATION_INSTRUCTIONS}\n"
        f"REPORT A (incoming)\n"
        f"  original: {incoming_original}\n"
        f"  english:  {incoming_text}\n"
        f"\n"
        f"REPORT B (already received)\n"
        f"  original: {neighbour.text_original}\n"
        f"  english:  {neighbour.text_en}\n"
        f"  division: {neighbour.gn_division_code}\n"
        f"  type:     {neighbour.incident_type}\n"
        f"  received: {neighbour.occurred_at.isoformat()}\n"
        f"  vector similarity: {neighbour.similarity:.3f}\n"
        f"  minutes apart: {minutes:.0f}\n"
        f"\nJSON:"
    )


def _parse(answer: str) -> tuple[bool, float, str]:
    """Pull the verdict out of a model's JSON.

    Raises:
        ValueError: for anything unparseable. The caller turns that into "separate, and
            flag", which is the safe direction.
    """
    body = answer.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()

    raw = json.loads(body)
    if not isinstance(raw, dict) or "same_incident" not in raw:
        raise ValueError("no same_incident field in the adjudication")

    return (
        bool(raw["same_incident"]),
        float(raw.get("confidence", 0.0)),
        str(raw.get("reasoning", ""))[:500],
    )
