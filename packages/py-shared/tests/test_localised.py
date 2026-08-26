import pytest
from pydantic import ValidationError
from sarana_shared.domain.localised import LocalisedText, PendingTranslation


def test_all_locales_required() -> None:
    text = LocalisedText(si="ආපදාව", ta="பேரிடர்", en="Disaster")
    assert text.get("si") == "ආපදාව"
    assert text.get("en") == "Disaster"
    assert text.as_dict() == {"si": "ආපදාව", "ta": "பேரிடர்", "en": "Disaster"}


def test_blank_locale_rejected() -> None:
    with pytest.raises(ValidationError):
        LocalisedText(si="", ta="x", en="x")


def test_missing_locale_rejected() -> None:
    with pytest.raises(ValidationError):
        LocalisedText.model_validate({"si": "x", "en": "x"})  # ta missing entirely


def test_pending_translation_from_partial() -> None:
    pending = PendingTranslation.from_partial({"en": "Flood warning"})
    assert pending.known == {"en": "Flood warning"}
    assert set(pending.missing) == {"si", "ta"}
    assert pending.reason == "awaiting_translation"


def test_pending_translation_rejects_already_complete() -> None:
    with pytest.raises(ValueError, match="should be a LocalisedText"):
        PendingTranslation.from_partial({"si": "x", "ta": "x", "en": "x"})
