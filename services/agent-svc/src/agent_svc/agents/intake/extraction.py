"""Pulling structure out of a report, and refusing the number that is not in it.

## `people_at_risk` is the dangerous field

It drives triage rank directly - it is 40% of the deterministic score - so a number this
agent invents decides who a crew is sent to first. A model asked "how many people are at
risk?" will answer. It will answer for a report that never said, because answering is what
it does, and the answer will look exactly like one that was read off the text.

So every `people_at_risk` carries `people_at_risk_basis`: the span of the **source text**
that justified it. `verify_basis` then checks that the basis is genuinely a substring of
the source, and an extraction that fails the check has its count stripped and is routed to a
person. Not corrected, not re-asked - stripped, because a number whose evidence turned out
not to exist is not a number worth keeping.

`None` and `0` are different answers and the model is told so. `None` means the report did
not say; `0` means it said nobody is at risk. A guessed 0 sorts an emergency to the bottom
of the queue, which is the same as losing it.

## The deterministic path is keyword matching and it is honest about that

With no model provider, extraction is `lexicon.py` over the text: incident types by
keyword, vulnerability groups by keyword, immediate danger by keyword, and **no people
count at all**. Counting people from keywords is not something a keyword can do, and
producing a low-confidence guess would be worse than the absence.

Everything from that path is labelled `DETERMINISTIC`, carries a confidence well below the
review threshold, and is routed for human confirmation. Slower, fully functional, clearly
labelled - which is the degraded path this platform promises everywhere.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

import structlog
from pydantic import ConfigDict, Field

from agent_svc.agents.intake import lexicon
from agent_svc.agents.intake.ports import ModelCall
from agent_svc.runtime.state import AgentOutput

_log = structlog.get_logger(__name__)

# The incident vocabulary, mirroring `incident.incident`'s CHECK. A type this agent extracts
# and the column rejects would fail at the INSERT, after the report was accepted and the
# citizen told it was received. A test asserts the two lists agree.
INCIDENT_TYPES: Final[tuple[str, ...]] = (
    "FLOOD",
    "LANDSLIDE",
    "STRUCTURAL_COLLAPSE",
    "MEDICAL",
    "MISSING_PERSON",
    "TRAPPED",
    "EVACUATION_NEEDED",
    "SUPPLIES_NEEDED",
    "INFRASTRUCTURE",
    "OTHER",
)

# The vulnerability groups triage weights. Same list as `lexicon.VULNERABILITY_TERMS`.
VULNERABLE_GROUPS: Final[tuple[str, ...]] = (
    "elderly",
    "children",
    "injured",
    "pregnant",
    "disabled",
)

# What the keyword path is worth. Below the 0.70 review threshold on purpose: everything it
# produces goes to a person, and a number that let it through a gate would be a number
# claiming this path is as good as reading the report.
DETERMINISTIC_CONFIDENCE: Final = 0.45

# What it is worth when even the lexicon found nothing. A report that matched no hazard word
# in any of three languages is one nobody should act on unread.
UNRECOGNISED_CONFIDENCE: Final = 0.10

# How much of the source a basis may be before it stops being evidence and starts being a
# copy of the report. A basis that is the whole text justifies nothing - it is the model
# saying "because of what it says".
MAX_BASIS_SHARE: Final = 0.9

# A people-at-risk count above this is not refused, but it is flagged. Sri Lanka's largest
# GN divisions hold a few thousand people; a single report claiming more than this is either
# a district-level statement somebody typed into a household report, or a mistake.
IMPLAUSIBLE_PEOPLE_AT_RISK: Final = 500


class ExtractedReport(AgentOutput):
    """What one report says, structured.

    Extends `AgentOutput`, so `confidence`, `reasoning`, `needs_human_review` and
    `review_reason` are mandatory and mean the same thing they mean in every other agent -
    the review queue and the gates read them without knowing which agent produced them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_type: str = Field(description="One of INCIDENT_TYPES. Never free text.")
    subtype: str | None = Field(default=None, max_length=64)

    people_at_risk: int | None = Field(
        default=None,
        ge=0,
        description="None when the report did not say. Never a guessed 0 - a guessed zero "
        "sorts a real emergency to the bottom of the queue.",
    )
    people_at_risk_basis: str = Field(
        default="",
        max_length=500,
        description="The span of the source text that justified the count. Checked against "
        "the source; an unsupported number is stripped.",
    )

    immediate_danger: bool = False
    location_text: str | None = Field(default=None, max_length=500)
    landmarks: list[str] = Field(default_factory=list)
    vulnerable_present: list[str] = Field(default_factory=list)
    requested_assistance: list[str] = Field(default_factory=list)

    def model_post_init(self, context: Any) -> None:
        super().model_post_init(context)
        if self.incident_type not in INCIDENT_TYPES:
            raise ValueError(
                f"{self.incident_type!r} is not an incident type the database accepts. "
                f"Known: {', '.join(INCIDENT_TYPES)}."
            )
        unknown = set(self.vulnerable_present) - set(VULNERABLE_GROUPS)
        if unknown:
            raise ValueError(
                f"unknown vulnerability groups: {', '.join(sorted(unknown))}. "
                f"Known: {', '.join(VULNERABLE_GROUPS)}."
            )


def normalise(text: str) -> str:
    """Collapse whitespace so a basis check is not defeated by a line break.

    A model quoting a report across two SMS segments returns the quote with the break
    normalised, and comparing raw would reject a basis that is genuinely present. Case is
    left alone: Sinhala and Tamil have no case, and lowercasing English would let a basis
    match text it does not actually quote.
    """
    return re.sub(r"\s+", " ", text).strip()


def verify_basis(basis: str, source: str) -> bool:
    """Whether the quoted evidence is genuinely in the source.

    The check that makes `people_at_risk` trustworthy. An empty basis fails: a count with
    no evidence at all is exactly the case this exists to catch.

    A basis that is almost the entire report also fails. Quoting everything justifies
    nothing - it is the model saying "because of what it says" - and it would let any
    number through by attaching the whole text to it.
    """
    quoted = normalise(basis)
    body = normalise(source)
    if not quoted or not body:
        return False
    if len(quoted) > len(body) * MAX_BASIS_SHARE:
        return False
    return quoted in body


def enforce_basis(extracted: ExtractedReport, *, source: str) -> ExtractedReport:
    """Strip a people count whose evidence is not in the source, and route it to a person.

    Stripped rather than corrected or re-asked. A number whose justification turned out not
    to exist is not a number worth keeping, and asking again spends a second call to get a
    second unverifiable answer.

    A report with no count at all passes untouched - `None` is a legitimate and common
    answer, and requiring evidence for the absence of a number would make silence fail.
    """
    if extracted.people_at_risk is None:
        return extracted

    if verify_basis(extracted.people_at_risk_basis, source):
        return extracted

    _log.error(
        "intake_people_at_risk_unsupported",
        claimed=extracted.people_at_risk,
        basis=extracted.people_at_risk_basis[:120],
        impact="the count was not in the report; it has been stripped and this report "
        "routed to a person. An unsupported count drives triage rank directly.",
    )
    return extracted.model_copy(
        update={
            "people_at_risk": None,
            "people_at_risk_basis": "",
            "needs_human_review": True,
            "review_reason": (
                "the extracted people-at-risk count quoted evidence that is not in the "
                "report; the count was removed"
            ),
        }
    )


def flag_implausible_count(extracted: ExtractedReport) -> ExtractedReport:
    """Route an implausibly large count to a person. Never reject it.

    Flagging is not rejection anywhere in this agent. A report claiming six hundred people
    are at risk might be a school, and the cost of a human spending twenty seconds on it is
    twenty seconds - while the cost of dropping a real one is a death.
    """
    if extracted.people_at_risk is None or extracted.people_at_risk <= IMPLAUSIBLE_PEOPLE_AT_RISK:
        return extracted

    return extracted.model_copy(
        update={
            "needs_human_review": True,
            "review_reason": (
                f"{extracted.people_at_risk} people at risk in one report is above the "
                f"{IMPLAUSIBLE_PEOPLE_AT_RISK} threshold; it may be a district figure "
                "entered as a household one. The report stands and is dispatchable."
            ),
        }
    )


def deterministic(text: str) -> ExtractedReport:
    """Extract by keyword, with no model at all.

    The degraded path, and the path every test in this agent runs by default. It produces
    a type, the vulnerability groups named, and whether the report sounds urgent. It
    produces **no people count**: counting people is not something a keyword list can do,
    and a low-confidence guess at the field that drives triage would be worse than the
    absence.
    """
    found = lexicon.incident_types_in(text)
    danger = lexicon.immediate_danger_in(text)
    vulnerable = lexicon.vulnerabilities_in(text)

    if not found:
        return ExtractedReport(
            incident_type="OTHER",
            confidence=UNRECOGNISED_CONFIDENCE,
            reasoning=(
                "no hazard word from the trilingual lexicon appears in this report; "
                "it was not classified"
            ),
            needs_human_review=True,
            review_reason="the keyword extractor could not place this report",
            immediate_danger=bool(danger),
            vulnerable_present=sorted(vulnerable),
            provenance="DETERMINISTIC",
        )

    incident_type, hits = found[0]
    evidence = ", ".join(hits[:4])
    return ExtractedReport(
        incident_type=incident_type,
        confidence=DETERMINISTIC_CONFIDENCE,
        reasoning=f"keyword match: {evidence}",
        # Always. This path is below the review threshold by design, and saying so on the
        # record rather than relying on the threshold means a change to the threshold
        # cannot quietly start auto-publishing keyword guesses.
        needs_human_review=True,
        review_reason=(
            "extracted by keyword matching with no model; a person confirms the type "
            "before this is acted on"
        ),
        immediate_danger=bool(danger),
        vulnerable_present=sorted(vulnerable),
        provenance="DETERMINISTIC",
    )


EXTRACTION_INSTRUCTIONS: Final = """You are extracting structured facts from an emergency \
report sent by a citizen in Sri Lanka during a disaster.

Return only JSON matching this shape:
{
  "incident_type": one of INCIDENT_TYPES,
  "subtype": short string or null,
  "people_at_risk": integer or null,
  "people_at_risk_basis": the exact words from the report that give the number, or "",
  "immediate_danger": true or false,
  "location_text": what the report says about where this is, or null,
  "landmarks": list of place names mentioned,
  "vulnerable_present": subset of VULNERABLE_GROUPS,
  "requested_assistance": list of short strings,
  "confidence": 0.0 to 1.0,
  "reasoning": one sentence an officer can read while deciding whether to agree
}

Rules you must follow:
- people_at_risk is null when the report does not say. Never guess a number, and never \
answer 0 unless the report says nobody is at risk.
- people_at_risk_basis must be copied exactly from the report. It is checked.
- Never output latitude or longitude. Locations are looked up, not produced.
- Do not translate place names.
"""


async def extract(
    text: str,
    *,
    call: ModelCall | None = None,
    original_text: str | None = None,
) -> ExtractedReport:
    """Extract from one report, falling back to keywords whenever the model cannot.

    `original_text` is the report in the language it was sent in. The basis check runs
    against **both** it and the working English text, because a model handed a translation
    quotes the translation - and rejecting a correctly-quoted basis for not appearing in
    the original would strip every count on every non-English report.

    Every failure lands on `deterministic()` rather than raising. A report that cannot be
    extracted is still a report, and it is still dispatchable on its channel metadata and
    its coordinate.
    """
    if call is None:
        return deterministic(text)

    prompt = (
        f"{EXTRACTION_INSTRUCTIONS}\n"
        f"INCIDENT_TYPES: {', '.join(INCIDENT_TYPES)}\n"
        f"VULNERABLE_GROUPS: {', '.join(VULNERABLE_GROUPS)}\n\n"
        f"Report:\n{text}\n"
    )

    try:
        answer = await call(prompt)
    except Exception as error:  # noqa: BLE001 - a report is never lost to a provider outage
        _log.warning(
            "intake_extraction_model_unavailable",
            error=type(error).__name__,
            impact="the keyword extractor ran instead; the report is queued for a person",
        )
        return deterministic(text)

    try:
        parsed = _as_extracted(answer)
    except (ValueError, TypeError) as error:
        _log.warning(
            "intake_extraction_unparseable",
            error=str(error)[:160],
            impact="the keyword extractor ran instead; the report is queued for a person",
        )
        return deterministic(text)

    sources = [source for source in (text, original_text) if source]
    if parsed.people_at_risk is not None and not any(
        verify_basis(parsed.people_at_risk_basis, source) for source in sources
    ):
        parsed = enforce_basis(parsed, source=text)

    return flag_implausible_count(parsed)


def _as_extracted(answer: str) -> ExtractedReport:
    """Parse a model's JSON into the model, or raise.

    Tolerates a fenced code block, because models emit them and refusing on a formatting
    detail would send a perfectly good extraction to the keyword path.

    Raises:
        ValueError: for anything that is not the expected object. The caller falls back.
    """
    body = answer.strip()
    if body.startswith("```"):
        body = body.split("```")[1] if "```" in body[3:] else body[3:]
        body = body.removeprefix("json").strip()

    raw = json.loads(body)
    if not isinstance(raw, dict):
        raise TypeError(f"expected a JSON object, got {type(raw).__name__}")

    needs_review = bool(raw.get("needs_human_review", False))
    reason = raw.get("review_reason")
    confidence = float(raw.get("confidence", 0.0))

    return ExtractedReport(
        incident_type=str(raw.get("incident_type", "OTHER")).upper(),
        subtype=raw.get("subtype"),
        people_at_risk=raw.get("people_at_risk"),
        people_at_risk_basis=str(raw.get("people_at_risk_basis") or ""),
        immediate_danger=bool(raw.get("immediate_danger", False)),
        location_text=raw.get("location_text"),
        landmarks=[str(name) for name in raw.get("landmarks", [])],
        vulnerable_present=[
            group for group in raw.get("vulnerable_present", []) if group in VULNERABLE_GROUPS
        ],
        requested_assistance=[str(item) for item in raw.get("requested_assistance", [])],
        confidence=confidence,
        reasoning=str(raw.get("reasoning", ""))[:2000],
        needs_human_review=needs_review,
        review_reason=str(reason) if reason else None,
        provenance="MODEL",
    )
