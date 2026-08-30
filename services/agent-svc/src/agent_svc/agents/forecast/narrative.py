"""Turning drivers into prose a GN officer can read, in three languages.

The second and last place this agent uses a model. The facts are already decided by the time
anything gets here - the class, the millimetres, the households - and the model's only job is
to say them in a sentence rather than a table.

## The post-check, which is the point of this module

**Output containing a number that is not in the drivers is rejected.** Not flagged, not
scored down: discarded, and the static template is used instead.

A hallucinated figure in this particular output is worse than in most. It reaches a GN
officer as a specific claim about their division, attributed to the government, at the hour
they are deciding whether to move people - and it will be believed, because everything
around it is true. "180 households" when the drivers say 140 is not a stylistic problem.

The check is deliberately blunt: pull every numeral out of the generated text, and if one is
not among the numbers we handed the model, throw the whole thing away. It has false
positives - a model writing "the next 24 hours" when 24 was not a driver loses a perfectly
good sentence - and that trade is correct. A sentence is cheap. The static template says the
same facts less gracefully, in all three languages, and nobody is misinformed.

## Trilingual is not negotiable

Every citizen-facing string exists in si, ta and en (non-negotiable #2), so the fallback is
a template in all three and the model is asked for all three. A narrative that comes back
missing Tamil is treated as a failed generation, not as two-thirds of a success.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Final

import structlog

from agent_svc.agents.forecast.scoring import Driver, ImpactScore

_log = structlog.get_logger(__name__)

LANGUAGES: Final[tuple[str, ...]] = ("si", "ta", "en")

# Numerals in the generated text. Matches integers and decimals, with or without thousands
# separators, so "1,240" and "1240" are both caught.
_NUMERAL = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Numbers a narrative may use without them appearing in the drivers. Every one is a fact
# about the *forecast window* rather than about the division, and refusing them would reject
# almost every well-formed sentence: "over the next 24 hours" is how a person says it.
ALWAYS_ALLOWED: Final[frozenset[float]] = frozenset({0.0, 24.0, 48.0, 72.0})

# How close a generated number has to be to a driver value to count as the same number. A
# model writing "146 mm" for a driver value of 146.4 is rounding, not inventing; one writing
# "180" is inventing. Absolute, in the units of the value, because rainfall and household
# counts live at very different magnitudes and a percentage tolerance would be far too
# generous on the larger of them.
ROUNDING_TOLERANCE: Final = 1.0

CLASS_WORDS: Final[dict[int, dict[str, str]]] = {
    0: {"si": "බලපෑමක් අපේක්ෂා නොකෙරේ", "ta": "பாதிப்பு எதிர்பார்க்கப்படவில்லை", "en": "no impact expected"},
    1: {"si": "අවම බලපෑමක්", "ta": "குறைந்த பாதிப்பு", "en": "low impact"},
    2: {"si": "මධ්‍යම බලපෑමක්", "ta": "மிதமான பாதிப்பு", "en": "moderate impact"},
    3: {"si": "බරපතළ බලපෑමක්", "ta": "கடுமையான பாதிப்பு", "en": "major impact"},
    4: {"si": "අතිශය බරපතළ බලපෑමක්", "ta": "மிகக் கடுமையான பாதிப்பு", "en": "severe impact"},
}

TEMPLATES: Final[dict[str, str]] = {
    "si": (
        "{division}: ඉදිරි පැය {lead} තුළ {klass}. අපේක්ෂිත වර්ෂාපතනය මිලිමීටර් {rain}. "
        "බලපෑමට ලක්විය හැකි ගෘහ ඒකක {households}. {road}"
    ),
    "ta": (
        "{division}: அடுத்த {lead} மணி நேரத்தில் {klass}. எதிர்பார்க்கப்படும் மழை {rain} மி.மீ. "
        "பாதிக்கப்படக்கூடிய குடும்பங்கள் {households}. {road}"
    ),
    "en": (
        "{division}: {klass} within the next {lead} hours. Expected rainfall {rain} mm. "
        "Households in the affected division: {households}. {road}"
    ),
}

ROAD_LOSS: Final[dict[str, str]] = {
    "si": "මාර්ග ප්‍රවේශය අහිමි විය හැක.",
    "ta": "சாலை அணுகல் துண்டிக்கப்படலாம்.",
    "en": "Road access is likely to be lost.",
}

ROAD_OK: Final[dict[str, str]] = {
    "si": "මාර්ග ප්‍රවේශය දැනට රැඳේ.",
    "ta": "சாலை அணுகல் தற்போது உள்ளது.",
    "en": "Road access is expected to hold.",
}


@dataclass(frozen=True, slots=True)
class Narrative:
    """The drivers, said in words, in three languages."""

    text: dict[str, str]
    # `TEMPLATE` or `LLM`. Carried onto the forecast so the UI can label a generated
    # sentence as generated, and so the eval report can say how often the model's output
    # survived the post-check.
    method: str

    @property
    def is_complete(self) -> bool:
        return all(self.text.get(language, "").strip() for language in LANGUAGES)


def allowed_numbers(score: ImpactScore, division_name: str = "") -> set[float]:
    """Every number the narrative is allowed to contain.

    The driver values and thresholds, the class, the lead time, the household count - and
    nothing else. Built from the score rather than from the prompt so a change to the
    prompt cannot quietly widen what the model may say.
    """
    numbers: set[float] = set(ALWAYS_ALLOWED)
    numbers.add(float(score.impact_class))
    numbers.add(float(score.lead_time_hours))
    numbers.add(float(score.expected_households_affected))

    for driver in score.drivers:
        for candidate in (driver.value, driver.threshold):
            numeric = _as_number(candidate)
            if numeric is not None:
                numbers.add(numeric)
            elif isinstance(candidate, str):
                # A threshold like "watch 100 / warning 150 / evacuate 200 mm over 24h"
                # states real figures the narrative may legitimately quote.
                numbers.update(float(match) for match in _NUMERAL.findall(candidate))

    # A division code contains digits, and a narrative naming the division is doing the
    # right thing. Without this every well-formed sentence fails the check.
    numbers.update(float(match.replace(",", "")) for match in _NUMERAL.findall(division_name))
    numbers.update(
        float(match.replace(",", "")) for match in _NUMERAL.findall(score.gn_division_code)
    )
    return numbers


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def invented_numbers(text: str, allowed: set[float]) -> list[str]:
    """Numerals in the text that are not among the allowed values.

    Returns them rather than a bool so the log line can name what was invented, which is
    the difference between "the check fired again" and a report somebody can act on.
    """
    found: list[str] = []
    for raw in _NUMERAL.findall(text):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:  # pragma: no cover - the pattern only matches parseable numerals
            continue
        if not any(abs(value - permitted) <= ROUNDING_TOLERANCE for permitted in allowed):
            found.append(raw)
    return found


def render_template(
    score: ImpactScore, *, division_name: dict[str, str] | None = None
) -> Narrative:
    """The static trilingual narrative. Never fails, never invents, always available.

    This is the degraded path, and it is also what a rejected generation falls back to.
    Written first, as build file 12 requires of every agent: an agent whose degraded path
    was an afterthought does not have one.
    """
    names = division_name or {}
    rain = next(
        (driver.value for driver in score.drivers if driver.factor == "peak_rainfall_24h"),
        0,
    )

    text = {}
    for language in LANGUAGES:
        road = (ROAD_LOSS if score.expected_road_access_loss else ROAD_OK)[language]
        text[language] = TEMPLATES[language].format(
            division=names.get(language) or score.gn_division_code,
            lead=score.lead_time_hours,
            klass=CLASS_WORDS[score.impact_class][language],
            rain=rain,
            households=score.expected_households_affected,
            road=road,
        )
    return Narrative(text=text, method="TEMPLATE")


PROMPT: Final = """Write a short impact statement for a Sri Lankan Grama Niladhari officer \
about their own division. Three languages: Sinhala (si), Tamil (ta), English (en).

Division: {division}
Impact class: {klass} of 4
Lead time: {lead} hours
Households in the division: {households}
Road access expected to be lost: {road}

What produced this assessment:
{drivers}

Answer with JSON only:
{{"si": "...", "ta": "...", "en": "..."}}

Rules:
- Two sentences per language at most. This is read on a phone, in the field, at night.
- **Use only the numbers given above.** Do not calculate, estimate, round to a different \
figure, or introduce any number not listed. A number you invent will be read as a \
government statement about this officer's own village.
- Say what to look at or do, not how the model works.
- Do not translate the English into the other two. Write each one as that language's \
speakers would say it."""


def build_prompt(score: ImpactScore, division_name: str) -> str:
    """The prompt, built here so a test can read exactly what the model is asked."""
    drivers = "\n".join(_describe(driver) for driver in score.drivers)
    return PROMPT.format(
        division=division_name or score.gn_division_code,
        klass=score.impact_class,
        lead=score.lead_time_hours,
        households=score.expected_households_affected,
        road="yes" if score.expected_road_access_loss else "no",
        drivers=drivers,
    )


def _describe(driver: Driver) -> str:
    parts = [f"- {driver.factor}: {driver.value}"]
    if driver.threshold is not None:
        parts.append(f"(threshold {driver.threshold})")
    if driver.note:
        parts.append(f"- {driver.note}")
    return " ".join(parts)


def parse_response(raw: str) -> dict[str, str] | None:
    """Extract the three languages, or None if any is missing.

    Missing Tamil is a failed generation, not two-thirds of a success. Non-negotiable #2 is
    not a quality target that degrades gracefully: a warning that reaches Sinhala and
    English speakers and not Tamil ones is the exact failure the rule exists to prevent.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        _log.warning("forecast_narrative_unparseable", response=raw[:200])
        return None

    if not isinstance(data, dict):
        return None

    rendered = {language: str(data.get(language, "")).strip() for language in LANGUAGES}
    if not all(rendered.values()):
        _log.warning(
            "forecast_narrative_incomplete",
            missing=[language for language, value in rendered.items() if not value],
            impact="a narrative missing a language is not published; the static template "
            "is used instead so every language says the same thing",
        )
        return None
    return rendered


async def explain(
    score: ImpactScore,
    *,
    division_name: dict[str, str] | None = None,
    call: Any = None,
) -> Narrative:
    """Write the narrative for one division's forecast.

    `call` is an async callable taking the prompt and returning the model's text. None takes
    the template path, and so does any failure, any incomplete response, and any output that
    fails the numeral check.
    """
    names = division_name or {}
    template = render_template(score, division_name=names)
    if call is None:
        return template

    try:
        raw = await call(build_prompt(score, names.get("en", "")))
    except Exception as error:  # noqa: BLE001 - a provider outage degrades, it does not fail
        _log.warning(
            "forecast_narrative_degraded",
            error=type(error).__name__,
            gn_division_code=score.gn_division_code,
            impact="the forecast is unchanged and published with its static narrative",
        )
        return template

    parsed = parse_response(str(raw))
    if parsed is None:
        return template

    allowed = allowed_numbers(score, names.get("en", ""))
    for language, sentence in parsed.items():
        invented = invented_numbers(sentence, allowed)
        if invented:
            _log.warning(
                "forecast_narrative_invented_numbers",
                language=language,
                numbers=invented,
                gn_division_code=score.gn_division_code,
                impact="the whole generation is discarded and the static template is "
                "published; a fabricated figure reaches a GN officer as a government "
                "statement about their own village",
            )
            return template

    return Narrative(text=parsed, method="LLM")
