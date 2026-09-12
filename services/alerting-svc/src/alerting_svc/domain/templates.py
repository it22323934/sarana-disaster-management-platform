"""Alert templates, and the two gates that stand between a template and a citizen.

A dispatched alert is a template plus typed parameters. Never a string a model produced at
dispatch time, and never free text a citizen sent us echoed back to a district.

**The trilingual review gate.** A template reaches PUBLISHED only when a named Sinhala
reviewer and a named Tamil reviewer have each signed off. Two different named people, both
recorded. Machine translation is not acceptable for a message that tells someone whether
to leave their house.

**The soft third gate.** An alert built entirely from a published template with valid
parameters dispatches automatically. An alert containing any free text goes to
PENDING_SIGNOFF and waits for a DMC operator. This is the one place where speed and
control genuinely trade off, and templates are how you get the speed without losing the
control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sarana_shared.domain.localised import REQUIRED_LOCALES

# `{gn_division_name}` - lowercase, underscores, nothing else. A permissive pattern here
# would let a template reference something that looks like a parameter and is not.
PARAMETER_PATTERN: Final = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# Parameters may only carry values from these sources. A citizen's own words never appear
# in an outbound warning: a district-wide SMS repeating text an attacker submitted is the
# obvious way to turn this platform into a megaphone.
ALLOWED_PARAMETER_TYPES: Final[tuple[str, ...]] = (
    "gn_division_name",
    "ds_division_name",
    "district_name",
    "shelter_name",
    "deadline_time",
    "effective_time",
    "water_level_m",
    "road_name",
    "distribution_point",
    "hazard_name",
)


class TemplateInvalid(ValueError):
    """The template cannot be used as it stands."""


class ReviewIncomplete(TemplateInvalid):
    """A template is missing a native reviewer's signature.

    Its own exception type because this is a release gate in CI, not a validation error a
    caller retries.
    """


@dataclass(frozen=True, slots=True)
class TemplateReview:
    """Who signed off which language."""

    reviewed_by_si: UUID | None
    reviewed_by_ta: UUID | None

    @property
    def complete(self) -> bool:
        return self.reviewed_by_si is not None and self.reviewed_by_ta is not None

    @property
    def missing(self) -> tuple[str, ...]:
        gaps = []
        if self.reviewed_by_si is None:
            gaps.append("si")
        if self.reviewed_by_ta is None:
            gaps.append("ta")
        return tuple(gaps)


def parameters_in(body: dict[str, str]) -> set[str]:
    """Every parameter name the body references, across all languages."""
    found: set[str] = set()
    for text in body.values():
        found |= set(PARAMETER_PATTERN.findall(text or ""))
    return found


def assert_body_is_trilingual(body: dict[str, str]) -> None:
    """Every locale present and non-blank.

    Raises:
        TemplateInvalid: naming the missing locales.
    """
    missing = [
        locale.value for locale in REQUIRED_LOCALES if not (body.get(locale.value) or "").strip()
    ]
    if missing:
        raise TemplateInvalid(
            f"a template body must carry all three languages; missing or blank: "
            f"{', '.join(missing)}"
        )


def assert_parameters_consistent(body: dict[str, str]) -> None:
    """Every language references the same parameters.

    A Sinhala body naming a shelter and a Tamil body omitting it would send two different
    warnings to two communities in the same division - which is precisely the failure this
    platform exists to correct.
    """
    per_language = {
        locale.value: set(PARAMETER_PATTERN.findall(body.get(locale.value) or ""))
        for locale in REQUIRED_LOCALES
    }
    reference = per_language[REQUIRED_LOCALES[0].value]
    for language, found in per_language.items():
        if found != reference:
            missing = reference - found
            extra = found - reference
            detail = []
            if missing:
                detail.append(f"missing {', '.join(sorted(missing))}")
            if extra:
                detail.append(f"unexpected {', '.join(sorted(extra))}")
            raise TemplateInvalid(
                f"the {language} body does not reference the same parameters as the "
                f"others: {'; '.join(detail)}. Two languages saying different things is "
                "the failure this platform exists to correct."
            )


def assert_parameters_known(body: dict[str, str]) -> None:
    """Every parameter is one the platform can fill from structured data."""
    unknown = parameters_in(body) - set(ALLOWED_PARAMETER_TYPES)
    if unknown:
        raise TemplateInvalid(
            f"unknown template parameters: {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(ALLOWED_PARAMETER_TYPES)}. A parameter that is not on this "
            "list would have to be filled from free text, which never enters an alert."
        )


def validate_template(body: dict[str, str]) -> None:
    """Every rule a template must satisfy before it can be reviewed."""
    assert_body_is_trilingual(body)
    assert_parameters_known(body)
    assert_parameters_consistent(body)


def assert_publishable(body: dict[str, str], review: TemplateReview) -> None:
    """Refuse to publish a template a native speaker has not signed off.

    Raises:
        ReviewIncomplete: naming the languages still unsigned. This is asserted in CI as
            well as here, because a template reaching PUBLISHED unreviewed is a wrong
            message sent to a whole district at once.
    """
    validate_template(body)
    if not review.complete:
        raise ReviewIncomplete(
            f"a template cannot be PUBLISHED without a named native reviewer for every "
            f"language; still unsigned: {', '.join(review.missing)}. Machine translation "
            "is not acceptable for a message that tells someone whether to leave home."
        )


@dataclass(frozen=True, slots=True)
class RenderResult:
    """A rendered template, and whether it needs a human before it goes out."""

    body: dict[str, str]
    used_parameters: dict[str, str]
    contains_free_text: bool

    @property
    def requires_signoff(self) -> bool:
        """The soft third gate."""
        return self.contains_free_text


def render(
    body: dict[str, str], parameters: dict[str, Any], *, free_text: dict[str, str] | None = None
) -> RenderResult:
    """Substitute parameters into every language.

    Substitution is by name and every parameter must be supplied - a template rendered
    with a missing parameter would go out reading "evacuate to {shelter_name}".

    `free_text` is accepted rather than refused so that an operator *can* write something
    the templates do not cover. It sets the flag that sends the alert to a human.

    Raises:
        TemplateInvalid: if a referenced parameter was not supplied.
    """
    required = parameters_in(body)
    missing = required - set(parameters)
    if missing:
        raise TemplateInvalid(
            f"template parameters not supplied: {', '.join(sorted(missing))}. "
            "An alert must never dispatch with an unfilled placeholder."
        )

    unknown = set(parameters) - set(ALLOWED_PARAMETER_TYPES)
    if unknown:
        raise TemplateInvalid(f"unknown parameters supplied: {', '.join(sorted(unknown))}")

    rendered: dict[str, str] = {}
    for locale in REQUIRED_LOCALES:
        code = locale.value
        text = body.get(code, "")
        for name, value in parameters.items():
            text = text.replace(f"{{{name}}}", str(value))
        if free_text and free_text.get(code):
            text = f"{text} {free_text[code]}".strip()
        rendered[code] = text

    return RenderResult(
        body=rendered,
        used_parameters={name: str(value) for name, value in parameters.items()},
        contains_free_text=bool(free_text and any(free_text.values())),
    )
