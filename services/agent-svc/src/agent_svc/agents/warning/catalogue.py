"""Choosing the template, and filling it from structured data.

**The model does not write alert text.** Alert text comes from a template a named Sinhala
reviewer and a named Tamil reviewer have each signed (file 09). What the model does here is
choose among that reviewed text and propose which structured value fills which parameter.
That is a real job. Generating warning copy at dispatch time is not one this platform is
willing to give a model: a hallucinated instruction in an evacuation order is an
unrecoverable harm, and it is unrecoverable specifically because the people acting on it
are the ones with the least time to check.

Two constraints sit around the model, and both are applied to its output rather than
requested in its prompt. A rule you ask a model to follow is a rule it follows most of the
time.

**It cannot choose a weaker template than the rules would have.** The deterministic matrix
below produces a floor, in CAP severity order, and a model answer below that floor is
discarded whole. The model can select a *different* template of equal or greater severity -
which is the case it is genuinely useful for, where two templates fit and one fits better -
and it can never turn a warning into a watch.

**It cannot invent a parameter value.** A proposed value is accepted only if it appears,
character for character, among the structured facts the caller supplied. Anything else is
free text with a template wrapped around it, and free text is the thing the whole soft
human gate exists to catch.

## When nothing fits

The agent does not improvise. `no_suitable_template` is a review item for a DMC operator,
who either picks one or authors an alert with free text - which then goes through the soft
human gate on its way out.

**A template that cannot be filled does not fall back to a weaker one.** If class 4 selects
`FLOOD_EVACUATE_IMMEDIATE` and no shelter has been named, the answer is a review item, not
`FLOOD_WARNING`. Quietly downgrading an evacuation order to a warning because a parameter
lookup came back empty is the exact category of silent failure this platform was built
after: it produces a message that goes out, reads as deliberate, and tells people to
prepare when they were meant to leave.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import structlog

from agent_svc.agents.warning.ports import AlertTemplate, ModelCall

_log = structlog.get_logger(__name__)

# CAP severity, ranked. The floor the model cannot be talked below.
SEVERITY_RANK: Final[dict[str, int]] = {
    "UNKNOWN": 0,
    "MINOR": 1,
    "MODERATE": 2,
    "SEVERE": 3,
    "EXTREME": 4,
}

# The deterministic matrix: (hazard type, impact class) to template code. This is the whole
# degraded path - with the model provider unreachable, an over-budget run, or no API key at
# all, template selection is this table and nothing else, and it is fully functional.
#
# Class 0 and 1 are deliberately absent everywhere. Class 1 means rain approaching a
# division's own threshold; a public alert at that level is the alert people learn to
# ignore before the one that matters arrives.
#
# LANDSLIDE has no evacuate-immediate template in the seeded twelve, so class 4 selects
# LANDSLIDE_WARNING - the most severe landslide text that has been through native review.
# That is a real gap in the catalogue rather than a modelling choice, it is recorded on the
# selection as a note, and the honest fix is a thirteenth template and two more signatures.
RULE_MATRIX: Final[dict[tuple[str, int], str]] = {
    ("FLOOD", 2): "FLOOD_WATCH",
    ("FLOOD", 3): "FLOOD_WARNING",
    ("FLOOD", 4): "FLOOD_EVACUATE_IMMEDIATE",
    ("LANDSLIDE", 2): "LANDSLIDE_WATCH",
    ("LANDSLIDE", 3): "LANDSLIDE_WARNING",
    ("LANDSLIDE", 4): "LANDSLIDE_WARNING",
    ("CYCLONE", 2): "CYCLONE_WARNING",
    ("CYCLONE", 3): "CYCLONE_WARNING",
    ("CYCLONE", 4): "CYCLONE_WARNING",
    ("STORM_SURGE", 2): "STORM_SURGE_WARNING",
    ("STORM_SURGE", 3): "STORM_SURGE_WARNING",
    ("STORM_SURGE", 4): "STORM_SURGE_WARNING",
}

# Hazard types with no warning template at all. DROUGHT is in the schema's vocabulary and
# none of the twelve seeded templates addresses it, which is a catalogue gap and not a bug:
# a drought warning is a different message on a different timescale, and improvising one
# from a flood template would be worse than routing to a person.
NO_TEMPLATE_HAZARDS: Final[frozenset[str]] = frozenset({"DROUGHT"})

# Confidence for a rule-selected template. High, because the matrix is a lookup rather than
# a judgement - what is uncertain about a warning is the forecast behind it, and that
# confidence travels separately.
RULE_CONFIDENCE: Final = 0.90

# What a model-confirmed choice is worth. Above the rule figure only when the model agreed
# with it; a model that picks a different template of equal severity is doing something
# genuinely uncertain and says so.
MODEL_AGREED_CONFIDENCE: Final = 0.93
MODEL_DIVERGED_CONFIDENCE: Final = 0.75


class NoSuitableTemplate(Exception):
    """Nothing in the published catalogue covers this forecast.

    Its own type because the graph routes on it: it becomes a review item for a DMC
    operator rather than a failed run. An agent that improvised here would be an agent
    writing evacuation copy, which is the one thing this design refuses.
    """


@dataclass(frozen=True, slots=True)
class TemplateChoice:
    """Which template, filled with what, and how the decision was made."""

    template: AlertTemplate
    parameters: dict[str, str]
    confidence: float
    method: str
    reasoning: str
    notes: tuple[str, ...] = ()

    @property
    def provenance(self) -> str:
        """How this was produced, as the audit log and the console read it.

        Three values, not two. A template a person chose is not a template a rule chose,
        and the officer reading the record afterwards decides differently depending on
        which - so `HUMAN` is distinguished rather than folded into `DETERMINISTIC`.
        """
        if self.method == "LLM":
            return "MODEL"
        return "HUMAN" if self.method == "HUMAN" else "DETERMINISTIC"

    def rendered(self) -> dict[str, str]:
        """The three language bodies, parameters substituted."""
        return self.template.render(self.parameters)


@dataclass(frozen=True, slots=True)
class SelectionFacts:
    """The structured values a template may be filled from.

    Every one of these comes from reference data or from the forecast. A citizen's own
    words never appear in an outbound warning: a district-wide SMS repeating text somebody
    submitted is the obvious way to turn this platform into a megaphone.
    """

    gn_division_name: str | None = None
    ds_division_name: str | None = None
    district_name: str | None = None
    shelter_name: str | None = None
    deadline_time: str | None = None
    effective_time: str | None = None
    water_level_m: str | None = None
    road_name: str | None = None
    distribution_point: str | None = None
    hazard_name: str | None = None

    def available(self) -> dict[str, str]:
        """The facts that actually have a value, keyed by parameter name."""
        return {
            name: value
            for name, value in (
                ("gn_division_name", self.gn_division_name),
                ("ds_division_name", self.ds_division_name),
                ("district_name", self.district_name),
                ("shelter_name", self.shelter_name),
                ("deadline_time", self.deadline_time),
                ("effective_time", self.effective_time),
                ("water_level_m", self.water_level_m),
                ("road_name", self.road_name),
                ("distribution_point", self.distribution_point),
                ("hazard_name", self.hazard_name),
            )
            if value is not None and str(value).strip()
        }


def rule_choice(hazard_type: str, impact_class: int) -> str | None:
    """The template code the matrix gives, or None if nothing covers this."""
    return RULE_MATRIX.get((hazard_type.upper(), impact_class))


def _by_code(catalogue: list[AlertTemplate]) -> dict[str, AlertTemplate]:
    return {template.code: template for template in catalogue}


def _fill(template: AlertTemplate, facts: dict[str, str]) -> dict[str, str]:
    """The parameter values this template needs, from the facts.

    Raises:
        NoSuitableTemplate: naming what is missing. See the module docstring on why this
            refuses rather than selecting a template with fewer parameters.
    """
    missing = sorted(template.parameters - set(facts))
    if missing:
        raise NoSuitableTemplate(
            f"{template.code} needs {', '.join(missing)} and no structured value is "
            "available for it. An operator picks a template or authors the alert; the "
            "agent does not fall back to a less severe template, because an evacuation "
            "order quietly downgraded to a warning is worse than one that waited."
        )
    return {name: facts[name] for name in sorted(template.parameters)}


def select_named(
    code: str, *, catalogue: list[AlertTemplate], facts: SelectionFacts
) -> TemplateChoice:
    """Use the template a named person asked for.

    This is the answer to `no_suitable_template`, and it deliberately does not consult the
    matrix: a DMC operator who knows the district has decided, and the matrix exists to act
    when nobody has. Their choice outranks it, and the provenance says a human made it.

    Two things still hold. The template must be **published** - a named Sinhala reviewer and
    a named Tamil reviewer have signed it - and it must be **fillable** from structured
    data. "The operator picked it" is not a reason to dispatch a message with
    `{shelter_name}` still in it, and it is not a reason to send unreviewed text.

    Raises:
        NoSuitableTemplate: if the code is not in the published catalogue, or cannot be
            filled. The graph asks once more rather than looping.
    """
    published = _by_code(catalogue)
    chosen = published.get(code.upper())
    if chosen is None:
        raise NoSuitableTemplate(
            f"{code!r} is not in the published catalogue. Published templates: "
            f"{', '.join(sorted(published)) or 'none'}."
        )

    return TemplateChoice(
        template=chosen,
        parameters=_fill(chosen, facts.available()),
        # A person's decision, and the confidence of one. Not the rule figure: this did not
        # come from the matrix and reporting it as though it had would hide who chose.
        confidence=1.0,
        method="HUMAN",
        reasoning=f"a DMC operator selected {chosen.code}",
    )


async def select(
    *,
    hazard_type: str,
    impact_class: int,
    catalogue: list[AlertTemplate],
    facts: SelectionFacts,
    call: ModelCall | None = None,
) -> TemplateChoice:
    """Choose a template and fill it.

    The rule matrix runs first and always. The model is asked only when there is more than
    one template it could reasonably be, and its answer is checked against the floor before
    it is used.

    Raises:
        NoSuitableTemplate: when the catalogue has nothing for this hazard and class, or
            when the template that fits cannot be filled from structured data. Both are
            review items rather than failures.
    """
    hazard = hazard_type.upper()
    available = facts.available()
    published = _by_code(catalogue)

    if hazard in NO_TEMPLATE_HAZARDS:
        raise NoSuitableTemplate(
            f"no published template addresses {hazard}. A {hazard.lower()} warning is a "
            "different message on a different timescale, and improvising one from a flood "
            "template would be worse than asking an operator."
        )

    code = rule_choice(hazard, impact_class)
    if code is None:
        raise NoSuitableTemplate(
            f"nothing in the matrix covers {hazard} at impact class {impact_class}. "
            "Classes 0 and 1 deliberately produce no public alert."
        )
    if code not in published:
        raise NoSuitableTemplate(
            f"{code} is the right template for {hazard} at class {impact_class} and it is "
            "not published. A template reaches PUBLISHED only when a named Sinhala "
            "reviewer and a named Tamil reviewer have each signed it."
        )

    floor = published[code]
    notes: list[str] = []
    if hazard == "LANDSLIDE" and impact_class >= 4:
        notes.append(
            "the catalogue has no landslide evacuate-immediate template; this is the most "
            "severe landslide text that has been through native review"
        )

    if call is None:
        return TemplateChoice(
            template=floor,
            parameters=_fill(floor, available),
            confidence=RULE_CONFIDENCE,
            method="RULE_MATRIX",
            reasoning=f"{hazard} at impact class {impact_class} selects {floor.code}",
            notes=tuple(notes),
        )

    return await _model_choice(
        floor=floor,
        hazard=hazard,
        impact_class=impact_class,
        published=published,
        available=available,
        notes=notes,
        call=call,
    )


async def _model_choice(
    *,
    floor: AlertTemplate,
    hazard: str,
    impact_class: int,
    published: dict[str, AlertTemplate],
    available: dict[str, str],
    notes: list[str],
    call: ModelCall,
) -> TemplateChoice:
    """Ask the model, then check its answer against the floor.

    Every failure mode here lands on the rule choice rather than raising: a model that is
    unreachable, slow, or returns something that is not a template code must not stop a
    warning going out. The run records which path produced the answer.
    """
    candidates = [
        template
        for template in published.values()
        if template.hazard_type.upper() == hazard
        and SEVERITY_RANK.get(template.severity.upper(), 0)
        >= SEVERITY_RANK.get(floor.severity.upper(), 0)
        and not (template.parameters - set(available))
    ]
    if len(candidates) < 2:
        return TemplateChoice(
            template=floor,
            parameters=_fill(floor, available),
            confidence=RULE_CONFIDENCE,
            method="RULE_MATRIX",
            reasoning=(
                f"{floor.code} is the only publishable template at or above this severity; "
                "no model call was worth making"
            ),
            notes=tuple(notes),
        )

    try:
        answer = (await call(_prompt(hazard, impact_class, candidates))).strip().upper()
    except Exception as error:  # noqa: BLE001 - a warning does not wait on a model provider
        _log.warning(
            "warning_template_model_unavailable",
            error=type(error).__name__,
            impact="the rule matrix selected the template; the alert is unaffected",
        )
        return TemplateChoice(
            template=floor,
            parameters=_fill(floor, available),
            confidence=RULE_CONFIDENCE,
            method="RULE_MATRIX",
            reasoning=f"the model provider was unreachable; {floor.code} by rule",
            notes=(*notes, "model unavailable"),
        )

    chosen = published.get(answer)
    if chosen is None or chosen.hazard_type.upper() != hazard:
        _log.warning(
            "warning_template_model_answer_rejected",
            answer=answer[:48],
            reason="not a published template for this hazard",
        )
        return TemplateChoice(
            template=floor,
            parameters=_fill(floor, available),
            confidence=RULE_CONFIDENCE,
            method="RULE_MATRIX",
            reasoning=f"the model named something outside the catalogue; {floor.code} by rule",
            notes=(*notes, "model answer outside the catalogue"),
        )

    if SEVERITY_RANK.get(chosen.severity.upper(), 0) < SEVERITY_RANK.get(floor.severity.upper(), 0):
        # The floor, applied to the output rather than requested in the prompt. This is the
        # case the whole constraint exists for: a model talking a warning down to a watch.
        _log.error(
            "warning_template_model_below_floor",
            chose=chosen.code,
            floor=floor.code,
            impact="the model's choice was less severe than the rules require; discarded",
        )
        return TemplateChoice(
            template=floor,
            parameters=_fill(floor, available),
            confidence=RULE_CONFIDENCE,
            method="RULE_MATRIX",
            reasoning=(
                f"the model chose {chosen.code}, below the severity {floor.code} requires; "
                "discarded"
            ),
            notes=(*notes, f"model choice {chosen.code} discarded: below the severity floor"),
        )

    agreed = chosen.code == floor.code
    return TemplateChoice(
        template=chosen,
        parameters=_fill(chosen, available),
        confidence=MODEL_AGREED_CONFIDENCE if agreed else MODEL_DIVERGED_CONFIDENCE,
        method="LLM",
        reasoning=(
            f"the model chose {chosen.code}"
            + ("; the rule matrix agrees" if agreed else f", over the matrix's {floor.code}")
        ),
        notes=tuple(notes),
    )


def _prompt(hazard: str, impact_class: int, candidates: list[AlertTemplate]) -> str:
    """The constrained-choice prompt.

    Nothing varying goes at the front: the instruction block is a stable prefix so prompt
    caching applies, and a correlation id interpolated into it would cost the cache hit on
    every call behind it.

    The English body is shown because it is what the operator would read. The Sinhala and
    Tamil bodies are not: they say the same thing, the model is choosing a code rather
    than reading copy, and three languages of twelve templates in every prompt is tokens
    spent on text nobody uses.
    """
    lines = [
        "You are selecting one alert template for a Sri Lankan disaster warning.",
        "Answer with exactly one template code from the list and nothing else.",
        "Do not write alert text. Do not explain.",
        "",
        "Templates:",
    ]
    lines += [
        f"- {template.code} (severity {template.severity}): {template.body.get('en', '')}"
        for template in sorted(candidates, key=lambda t: t.code)
    ]
    lines += [
        "",
        f"Hazard: {hazard}",
        f"Predicted impact class: {impact_class} (0 none, 2 moderate, 3 major, 4 severe)",
        "",
        "Template code:",
    ]
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ParameterProposal:
    """A model's suggested parameter fill, and what survived checking."""

    accepted: dict[str, str] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.rejected


def validate_parameters(
    proposed: dict[str, str], *, facts: dict[str, str], allowed: frozenset[str]
) -> ParameterProposal:
    """Keep only proposed values that are verbatim structured facts.

    The second constraint from the module docstring. A model may say which of several known
    values fits a parameter; it may not supply the value. `shelter_name` filled with "the
    temple on the hill" is not a shelter name the platform knows, and a template rendered
    around it is free text with a template around it.
    """
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}

    for name, value in proposed.items():
        if name not in allowed:
            rejected[name] = value
        elif facts.get(name) == value:
            accepted[name] = value
        else:
            rejected[name] = value

    if rejected:
        _log.error(
            "warning_parameter_values_rejected",
            parameters=sorted(rejected),
            impact="the model proposed values that are not structured facts; the "
            "deterministic fill was used instead",
        )
    return ParameterProposal(accepted=accepted, rejected=rejected)
