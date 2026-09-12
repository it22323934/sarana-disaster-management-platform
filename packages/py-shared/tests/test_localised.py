"""Trilingual text - the invariant, not a feature."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sarana_shared.domain.localised import (
    Locale,
    LocalisedText,
    check_completeness,
    parse_accept_language,
)


def test_all_three_locales_are_required() -> None:
    text = LocalisedText(si="ආයුබෝවන්", ta="வணக்கம்", en="Hello")

    assert text.get(Locale.TA) == "வணக்கம்"


def test_a_two_language_record_cannot_be_constructed() -> None:
    """The Ditwah failure in type form.

    The 28 Nov 2025 DMC press conference went out in Sinhala and English only. There is
    no constructor path here that reproduces that.
    """
    with pytest.raises(ValidationError):
        LocalisedText(si="රතු අනතුරු ඇඟවීම", en="Red alert")  # type: ignore[call-arg]  # the point of the test


def test_a_blank_translation_is_not_a_translation() -> None:
    with pytest.raises(ValidationError):
        LocalisedText(si="පණිවිඩය", ta="   ", en="Message")


def test_an_unknown_locale_falls_back_without_raising() -> None:
    """A citizen with an unusual device setting still gets a readable string."""
    text = LocalisedText(si="ජලය", ta="தண்ணீர்", en="Water")

    assert text.get("fr") == "Water"


def test_completeness_names_what_is_missing() -> None:
    result = check_completeness({"si": "ජලය", "en": "Water"})

    assert not result.complete
    assert result.missing == ("ta",)
    assert "ta" in result.reason


def test_completeness_rejects_a_non_mapping() -> None:
    result = check_completeness("just a string")

    assert not result.complete
    assert result.missing == ("si", "ta", "en")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("ta", Locale.TA),
        ("ta-LK,ta;q=0.9,en;q=0.8", Locale.TA),
        ("si-LK", Locale.SI),
        ("fr-FR,fr;q=0.9", Locale.EN),
        (None, Locale.EN),
        ("", Locale.EN),
        ("en;q=0.4,ta;q=0.9", Locale.TA),
    ],
)
def test_accept_language_negotiation(header: str | None, expected: Locale) -> None:
    assert parse_accept_language(header) is expected
