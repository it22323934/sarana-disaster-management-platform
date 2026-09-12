"""The trilingual gate: no life-safety message goes out in fewer than three languages.

Named in the definition of done as its own suite because it is the rule most likely to be
quietly relaxed under deadline pressure. Relaxing it means a Tamil-speaking household in a
majority-Sinhala division gets a warning they cannot read, which is the exact failure this
platform exists to correct.

Two independent gates are tested here:

  1. A template cannot reach PUBLISHED without a **named** Sinhala reviewer and a **named**
     Tamil reviewer. Machine translation is never acceptable for this.
  2. A CAP document with fewer than three complete `<info>` blocks is refused at dispatch.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from alerting_svc.domain import cap, templates
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now


def a_body(**overrides: str) -> dict[str, str]:
    body = {
        "si": "{gn_division_name} ප්‍රදේශයේ ජනතාව {shelter_name} වෙත යන්න",
        "ta": "{gn_division_name} பகுதி மக்கள் {shelter_name} செல்லவும்",
        "en": "Residents of {gn_division_name} move to {shelter_name}",
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------------------
# Gate 1: the native review signatures
# --------------------------------------------------------------------------------------


def test_a_fully_reviewed_template_can_be_published() -> None:
    review = templates.TemplateReview(reviewed_by_si=uuid7(), reviewed_by_ta=uuid7())

    templates.assert_publishable(a_body(), review)


def test_a_template_without_a_tamil_reviewer_cannot_be_published() -> None:
    """The case the brief names. Also a CI gate."""
    review = templates.TemplateReview(reviewed_by_si=uuid7(), reviewed_by_ta=None)

    with pytest.raises(templates.ReviewIncomplete) as caught:
        templates.assert_publishable(a_body(), review)

    assert "ta" in str(caught.value)


def test_a_template_without_a_sinhala_reviewer_cannot_be_published() -> None:
    review = templates.TemplateReview(reviewed_by_si=None, reviewed_by_ta=uuid7())

    with pytest.raises(templates.ReviewIncomplete):
        templates.assert_publishable(a_body(), review)


def test_an_unreviewed_template_names_both_missing_languages() -> None:
    """An operator fixing this wants the whole list, not the first problem."""
    review = templates.TemplateReview(reviewed_by_si=None, reviewed_by_ta=None)

    assert review.missing == ("si", "ta")


def test_reviewers_are_recorded_by_identity_not_by_a_boolean() -> None:
    """ "Reviewed" with nobody's name against it is not a review."""
    reviewer = uuid7()
    review = templates.TemplateReview(reviewed_by_si=reviewer, reviewed_by_ta=uuid7())

    assert review.reviewed_by_si == reviewer
    assert review.complete


# --------------------------------------------------------------------------------------
# Gate 1b: the template body itself
# --------------------------------------------------------------------------------------


def test_a_two_language_template_is_refused() -> None:
    with pytest.raises(templates.TemplateInvalid, match="all three languages"):
        templates.validate_template({"si": "x", "en": "y"})


def test_a_blank_translation_is_refused() -> None:
    """Whitespace is not a translation."""
    with pytest.raises(templates.TemplateInvalid, match="all three languages"):
        templates.validate_template(a_body(ta="   "))


def test_languages_referencing_different_parameters_are_refused() -> None:
    """Two languages saying different things is the failure this platform corrects.

    A Sinhala body naming a shelter and a Tamil body omitting it sends two different
    warnings to two communities in the same division.
    """
    with pytest.raises(templates.TemplateInvalid, match="same parameters"):
        templates.validate_template(a_body(ta="{gn_division_name} பகுதி மக்கள் வெளியேறவும்"))


def test_an_unknown_parameter_is_refused() -> None:
    """Every parameter must be fillable from structured data.

    One that is not would have to come from free text, and free text never enters an
    alert body.
    """
    with pytest.raises(templates.TemplateInvalid, match="unknown template parameters"):
        templates.validate_template(
            {
                "si": "{citizen_message}",
                "ta": "{citizen_message}",
                "en": "{citizen_message}",
            }
        )


# --------------------------------------------------------------------------------------
# Gate 2: the CAP document at dispatch
# --------------------------------------------------------------------------------------


def an_alert(**overrides: object) -> cap.CapAlert:
    now = utc_now()
    fields: dict[str, object] = {
        "identifier": "sarana.lk.2026.0001",
        "sender": "dmc@sarana.lk",
        "sent": now,
        "msg_type": "Alert",
        "status": "Actual",
        "scope": "Public",
        "event": "Flood",
        "category": "Met",
        "severity": "Severe",
        "urgency": "Immediate",
        "certainty": "Observed",
        "headline": {"si": "ගංවතුර", "ta": "வெள்ளம்", "en": "Flood warning"},
        "description": {"si": "ජලය", "ta": "நீர்", "en": "Rising water"},
        "instruction": {"si": "යන්න", "ta": "செல்", "en": "Move to higher ground"},
        "effective": now,
        "expires": now + timedelta(hours=6),
        "area": cap.Area(gn_codes=["LK-21-01-001"]),
    }
    fields.update(overrides)
    return cap.CapAlert(**fields)  # type: ignore[arg-type]


def test_a_trilingual_alert_validates() -> None:
    cap.validate(an_alert())


def test_a_two_language_alert_is_rejected() -> None:
    """The case the brief names."""
    with pytest.raises(cap.CapInvalid) as caught:
        cap.validate(an_alert(headline={"si": "ගංවතුර", "en": "Flood warning"}))

    assert any("ta" in problem for problem in caught.value.problems)


def test_a_blank_instruction_in_one_language_is_rejected() -> None:
    """The instruction is the part that tells someone what to do."""
    with pytest.raises(cap.CapInvalid):
        cap.validate(an_alert(instruction={"si": "යන්න", "ta": "", "en": "Move to higher ground"}))


def test_the_generated_document_carries_one_info_block_per_language() -> None:
    xml = cap.to_xml(an_alert())

    assert xml.count("<info>") == 3
    for language in ("si-LK", "ta-LK", "en-LK"):
        assert f"<language>{language}</language>" in xml


def test_a_generated_document_reparses_without_structural_problems() -> None:
    """The CLI gate reads stored artefacts, so what is written must pass what reads it."""
    assert cap.parse_problems(cap.to_xml(an_alert())) == []


def test_a_document_missing_a_language_fails_the_cli_gate() -> None:
    """Hand-built, because the builder cannot produce one - which is the point."""
    xml = cap.to_xml(an_alert()).replace("<language>ta-LK</language>", "<language>en-LK</language>")

    problems = cap.parse_problems(xml)

    assert problems
    assert any("languages must be exactly" in problem for problem in problems)
