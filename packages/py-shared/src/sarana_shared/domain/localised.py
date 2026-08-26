"""LocalisedText — the trilingual field type used on every citizen-facing string.

Per docs/build-prompts/00-master-context.md: "No citizen-facing record may exist in only
one language" is a non-negotiable, enforced by schema and CI, not just convention. This
Pydantic model is the application-layer half of that; db/base.py's `all_locales_present`
Postgres constraint is the database-layer half. Both must hold — neither alone is enough.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

Locale = Literal["si", "ta", "en"]
SUPPORTED_LOCALES: tuple[Locale, ...] = ("si", "ta", "en")


class LocalisedText(BaseModel):
    """All three locales are required and non-empty. There is no nullable variant and
    no single-string fallback — if a translation isn't available yet, the record
    doesn't get written; it goes to a pending_translation queue instead."""

    si: str
    ta: str
    en: str

    @field_validator("si", "ta", "en")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("LocalisedText fields must be non-empty")
        return value

    def get(self, locale: Locale) -> str:
        match locale:
            case "si":
                return self.si
            case "ta":
                return self.ta
            case "en":
                return self.en

    def as_dict(self) -> dict[Locale, str]:
        return {"si": self.si, "ta": self.ta, "en": self.en}


class PendingTranslation(BaseModel):
    """What a LocalisedText field becomes when a translation isn't ready yet — an
    explicit queue entry, never a partially-filled or nullable LocalisedText."""

    known: dict[Locale, str]
    missing: list[Locale]
    reason: str = "awaiting_translation"

    @classmethod
    def from_partial(cls, partial: dict[Locale, str]) -> PendingTranslation:
        missing = [
            loc for loc in SUPPORTED_LOCALES if loc not in partial or not partial[loc].strip()
        ]
        if not missing:
            raise ValueError("All locales present — this should be a LocalisedText, not pending")
        return cls(
            known={k: v for k, v in partial.items() if k in SUPPORTED_LOCALES}, missing=missing
        )
