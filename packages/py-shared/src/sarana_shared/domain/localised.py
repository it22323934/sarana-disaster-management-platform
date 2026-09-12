"""Trilingual text - a hard system property, not a feature.

Non-negotiable #2 in the master context: no citizen-facing record may exist in only one
language. During Cyclone Ditwah the 28 Nov 2025 DMC/Defence Ministry press conference was
Sinhala and English only, and Tamil-speaking communities were left out. That failure is
why this type has no nullable variant and no single-string fallback.

If a translation is unavailable at write time the record does not get written - it goes
to the pending_translation queue instead.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Locale(StrEnum):
    """The three locales SARANA is required to serve."""

    SI = "si"
    TA = "ta"
    EN = "en"


REQUIRED_LOCALES: Final[tuple[Locale, ...]] = (Locale.SI, Locale.TA, Locale.EN)

DEFAULT_LOCALE: Final = Locale.EN

# Non-empty after stripping. A field of spaces is a missing translation wearing a hat.
NonBlankStr = Annotated[str, Field(min_length=1)]


class LocalisedText(BaseModel):
    """A citizen-facing string in all three locales. All three are required.

    Stored as JSONB with a Postgres CHECK constraint mirroring this validation, so the
    guarantee holds even for writes that bypass the application layer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    si: NonBlankStr
    ta: NonBlankStr
    en: NonBlankStr

    @model_validator(mode="after")
    def _reject_blank(self) -> Self:
        blank = [locale for locale in REQUIRED_LOCALES if not getattr(self, locale.value).strip()]
        if blank:
            missing = ", ".join(sorted(locale.value for locale in blank))
            raise ValueError(
                f"LocalisedText is blank in: {missing}. "
                "Route the record to the pending_translation queue rather than "
                "writing it in fewer than three languages."
            )
        return self

    def get(self, locale: Locale | str, *, fallback: Locale = DEFAULT_LOCALE) -> str:
        """Return the text for a locale.

        The fallback exists for unrecognised Accept-Language values, not for missing
        translations - by construction there are none.
        """
        key = locale.value if isinstance(locale, Locale) else str(locale).lower()[:2]
        if key not in {locale.value for locale in REQUIRED_LOCALES}:
            key = fallback.value
        value: str = getattr(self, key)
        return value

    def as_dict(self) -> dict[str, str]:
        """Plain dict for JSONB storage."""
        return {"si": self.si, "ta": self.ta, "en": self.en}


class TranslationCompleteness(BaseModel):
    """The result of checking a candidate payload for trilingual completeness."""

    model_config = ConfigDict(frozen=True)

    complete: bool
    missing: tuple[str, ...] = ()
    blank: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        """Human-readable explanation, safe to surface in a ProblemDetail `detail`."""
        if self.complete:
            return "all three locales present"
        parts = []
        if self.missing:
            parts.append(f"missing: {', '.join(self.missing)}")
        if self.blank:
            parts.append(f"blank: {', '.join(self.blank)}")
        return "; ".join(parts)


def check_completeness(value: Any) -> TranslationCompleteness:
    """Check an arbitrary mapping for si/ta/en completeness without raising.

    Used by the ingestion path to decide between writing a record and queueing it for
    translation, and by the CI i18n check over seed data.
    """
    if not isinstance(value, dict):
        return TranslationCompleteness(
            complete=False,
            missing=tuple(locale.value for locale in REQUIRED_LOCALES),
        )

    missing: list[str] = []
    blank: list[str] = []
    for locale in REQUIRED_LOCALES:
        if locale.value not in value:
            missing.append(locale.value)
            continue
        text = value[locale.value]
        if not isinstance(text, str) or not text.strip():
            blank.append(locale.value)

    return TranslationCompleteness(
        complete=not missing and not blank,
        missing=tuple(missing),
        blank=tuple(blank),
    )


def parse_accept_language(header: str | None, *, default: Locale = DEFAULT_LOCALE) -> Locale:
    """Pick a supported locale from an Accept-Language header.

    Respects q-values. Unsupported languages fall back to `default` rather than erroring -
    a citizen with an unusual browser setting still gets a readable page.
    """
    if not header:
        return default

    ranked: list[tuple[float, Locale]] = []
    for index, part in enumerate(header.split(",")):
        token = part.strip()
        if not token:
            continue
        tag, _, params = token.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        primary = tag.strip().lower().split("-")[0]
        for locale in REQUIRED_LOCALES:
            if primary == locale.value:
                # Index breaks ties in header order, which is the documented behaviour.
                ranked.append((quality - index * 1e-6, locale))

    if not ranked:
        return default
    return max(ranked, key=lambda pair: pair[0])[1]
