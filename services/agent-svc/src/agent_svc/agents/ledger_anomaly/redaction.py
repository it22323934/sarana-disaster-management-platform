"""The post-check that stands between a model and somebody's career.

Build file 17 requires this shipped and tested, and ADR-009 is why. Two rules, both applied
to model output rather than requested in a prompt — a rule you ask a model to follow is a
rule it follows most of the time, and "most of the time" is not the standard for a document
that can end a career on a statistical artifact.

**No individual may be named.** Not in the summary, not in the explanations, not in the
suggested actions. Checked structurally — ids, and anything shaped like a personal name in
a field that should contain neither.

**No accusatory or conclusive language.** A flag says "this pattern warrants review". It
does not say fraud, and it does not say misuse. The deny-list below is shipped, tested, and
deliberately blunt: a false rejection costs one template-rendered flag, and a false
acceptance puts an accusation into a record that a district secretary will read.

## Why a deny-list and not a classifier

A classifier would be better at catching paraphrase and worse at being auditable. Somebody
has to be able to read the list, argue with it, and add to it after an incident — and a
model deciding whether another model was accusatory is a second thing that can be wrong in
the same direction. The list is the floor, not the ceiling; `is_conclusive` also rejects the
grammatical shapes that make a claim without using any of the words.

## What happens to a rejected output

The whole context is discarded and the flag falls back to the template block, marked
`context_unavailable`. Not repaired, not re-asked: an output that reached for an accusation
once is not one to negotiate with, and the templated flag is a complete, usable, honest
artefact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

import structlog

_log = structlog.get_logger(__name__)

# Words that turn a question into an accusation. Shipped and tested, per build file 17.
#
# Stems rather than whole words, so "fraudulent", "corruption" and "falsified" are caught by
# the same entries. Blunt on purpose - see the module docstring on which error is cheaper.
ACCUSATORY_TERMS: Final[tuple[str, ...]] = (
    "fraud",
    "corrupt",
    "misuse",
    "misappropriat",
    "embezzl",
    "fake",
    "falsif",
    "forged",
    "theft",
    "steal",
    "stole",
    "bribe",
    "kickback",
    "collusion",
    "collud",
    "criminal",
    "dishonest",
    "deliberate manipulation",
    "intentionally inflated",
    "cover-up",
    "scam",
)

# Shapes that make a finding without using any of the words above. A model told not to say
# "fraud" will say "this indicates deliberate wrongdoing", and the sentence does the same
# damage.
CONCLUSIVE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\b(?:is|are|was|were)\s+(?:clearly|obviously|certainly|definitely)\b", re.I),
    re.compile(r"\bevidence\s+of\b", re.I),
    re.compile(r"\bproves?\s+that\b", re.I),
    re.compile(r"\bindicat\w*\s+(?:wrongdoing|misconduct|manipulation)\b", re.I),
    re.compile(r"\bshould\s+be\s+(?:disciplined|suspended|dismissed|prosecuted|reported)\b", re.I),
    re.compile(r"\b(?:guilty|culpable|responsible\s+for\s+the\s+discrepanc)\w*\b", re.I),
)

# A UUID in any casing. The database CHECK rejects a rationale containing a user id at any
# depth; this catches it a layer earlier, where the message can say why.
UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I
)

# Two or more capitalised words in a row - the shape of a personal name in any of the three
# scripts' romanisations. Deliberately crude, and the allow-list below is what stops it
# rejecting every sentence containing a place.
NAME_SHAPED: Final = re.compile(r"\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b")

# Capitalised pairs that are places, institutions or vocabulary rather than people. Without
# these the name check would reject "Kandy District" and "Grama Niladhari" and the
# contextualiser would never produce a usable sentence.
NOT_A_NAME: Final[frozenset[str]] = frozenset(
    {
        "grama niladhari",
        "divisional secretariat",
        "district secretariat",
        "disaster management",
        "impact class",
        "cell coverage",
        "survey team",
        "house full",
        "house partial",
        "household goods",
        "livelihood tools",
        "fishing gear",
        "cost schedule",
        "sri lanka",
        "kandy district",
        "north central",
        "north western",
        "total loss",
        "confirmation rate",
        "approval velocity",
        "evidence reuse",
        "category drift",
        "temporal burst",
        "value distribution",
        "duplicate household",
        "confirmation gap",
    }
)


@dataclass(frozen=True, slots=True)
class Rejection:
    """Why a model's context was refused, in enough detail to fix the prompt."""

    rule: str
    detail: str
    matched: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"rule": self.rule, "detail": self.detail, "matched": self.matched}


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Whether a document may be published, and everything wrong with it if not."""

    rejections: list[Rejection] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.rejections

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "rejections": [item.as_dict() for item in self.rejections],
        }


def _strings(value: Any) -> list[str]:
    """Every string anywhere in a nested document.

    Recursive because the check has to hold at any depth: a model that puts a name in
    `innocent_explanations[2]` has named somebody just as surely as one that puts it in the
    summary, and the database CHECK behind this looks at any depth too.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list | tuple):
        return [text for item in value for text in _strings(item)]
    return []


def names_individual(text: str) -> str | None:
    """The first thing in this text that looks like it identifies a person, or None."""
    found = UUID_PATTERN.search(text)
    if found:
        return found.group(0)

    for candidate in NAME_SHAPED.findall(text):
        if str(candidate).lower() not in NOT_A_NAME:
            return str(candidate)
    return None


def is_accusatory(text: str) -> str | None:
    """The first accusatory term in this text, or None."""
    lowered = text.lower()
    for term in ACCUSATORY_TERMS:
        if term in lowered:
            return term
    return None


def is_conclusive(text: str) -> str | None:
    """The first conclusive construction in this text, or None.

    Separate from the deny-list because these are shapes rather than words. A model told
    not to say "fraud" will write "this is clearly evidence of deliberate manipulation",
    and every word in that sentence is allowed.
    """
    for pattern in CONCLUSIVE_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(0)
    return None


def check(document: Any) -> CheckResult:
    """Every rule, over every string in the document.

    All rules run rather than stopping at the first. An output that names somebody *and*
    accuses them is a different kind of wrong from one that only does one, and whoever
    tunes the prompt afterwards wants both.
    """
    rejections: list[Rejection] = []

    for text in _strings(document):
        named = names_individual(text)
        if named:
            rejections.append(
                Rejection(
                    rule="no_individual_named",
                    detail=(
                        "ADR-009: no output of this agent may name an individual. A flag "
                        "against a named officer can end a career on a statistical "
                        "artifact, and the divisions that were hit hardest will "
                        "legitimately look like outliers."
                    ),
                    matched=named,
                )
            )

        accusatory = is_accusatory(text)
        if accusatory:
            rejections.append(
                Rejection(
                    rule="no_accusatory_language",
                    detail=(
                        "a flag says a pattern warrants review; it never states a finding. "
                        f"The term {accusatory!r} makes a claim this agent is not entitled "
                        "to make and no reviewer asked it to."
                    ),
                    matched=accusatory,
                )
            )

        conclusive = is_conclusive(text)
        if conclusive:
            rejections.append(
                Rejection(
                    rule="no_conclusive_language",
                    detail=(
                        "the phrasing states a conclusion rather than a pattern. A flag is "
                        "a question put to a human, and one that arrives already answered "
                        "is not a question."
                    ),
                    matched=conclusive,
                )
            )

    if rejections:
        _log.error(
            "anomaly_context_rejected",
            rules=sorted({item.rule for item in rejections}),
            impact="the model's context was discarded whole; the flag falls back to the "
            "template block and is marked context_unavailable",
        )
    return CheckResult(rejections=rejections)


def assert_publishable(document: Any) -> None:
    """Raise unless the document may be shown to a reviewer.

    Raises:
        ValueError: naming every rule that failed. Used where there is no template
            fallback - the graph prefers `check` and degrades, but a caller that has no
            second option must not proceed on a document that failed this.
    """
    result = check(document)
    if not result.clean:
        rules = ", ".join(sorted({item.rule for item in result.rejections}))
        raise ValueError(f"this document may not be published: {rules}")
