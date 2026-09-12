"""Extraction, the people-at-risk post-check, language detection, and geolocation.

Two refusals carry this file, and both are cases where the agent produces *less* than it
could and that is the correct behaviour.

**A count whose evidence is not in the report is stripped.** `people_at_risk` is 40% of the
triage score, so a number this agent invents decides who a crew reaches first. The basis
check is what makes the number trustworthy, and it is the single most important assertion
in the intake agent.

**An ambiguous landmark produces a division and no point.** A model asked for coordinates
returns plausible wrong ones; a gazetteer with two equally good matches must not pick. A
division-level incident is valid and dispatchable, and it is honest.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.intake import extraction, geolocate, lexicon
from agent_svc.agents.intake.ports import RawReport
from incident_svc.repo.incidents import INCIDENT_TYPES as SCHEMA_INCIDENT_TYPES
from tests.agents.intake.conftest import (
    DIVISION,
    GAMPOLA_LAT,
    GAMPOLA_LON,
    NOW,
    OTHER_DIVISION,
    BrokenCall,
    FakeGazetteer,
    RecordingCall,
    place,
)

# Real sentences in the three languages, of the kind that actually arrive by SMS.
SINHALA_FLOOD = "ගම්පොල ප්‍රදේශයේ ගංවතුර. උදව් අවශ්‍යයි."
TAMIL_COLLAPSE = "வீடு இடிந்து விழுந்தது. இரண்டு குழந்தை உள்ளே."
ENGLISH_TRAPPED = "Our house collapsed in Gampola, two children trapped inside, help us now"


# ---------------------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (SINHALA_FLOOD, "si"),
        (TAMIL_COLLAPSE, "ta"),
        (ENGLISH_TRAPPED, "en"),
    ],
)
def test_language_is_detected_from_the_script(text: str, expected: str) -> None:
    """Sinhala and Tamil occupy disjoint Unicode blocks, so this is exact and free.

    Spending a model call on this would be slower, cost money, and be less reliable than a
    character range check.
    """
    assert lexicon.detect(text).primary == expected


def test_code_switching_is_reported_rather_than_resolved() -> None:
    """Normal in Sri Lanka, and the hardest input this platform receives.

    It is also what upgrades the model tier, so collapsing a mixed report to one winner
    would route it to the cheap model at exactly the wrong moment.
    """
    mix = lexicon.detect("ගම්පොල Gampola flood ගංවතුර help needed urgently please")

    assert mix.code_switched
    assert set(mix.languages) == {"si", "en"}


def test_a_report_with_no_letters_does_not_claim_to_be_english() -> None:
    """A bare phone number or a GPS ping is not an English report.

    Letting digits vote would make every numeric SMS look confidently English and route it
    to an English reviewer.
    """
    mix = lexicon.detect("0771234567")

    assert mix.letters == 0
    assert mix.confidence == 0.0


def test_an_incidental_place_name_does_not_change_the_language() -> None:
    """One Sinhala word in an English sentence is an English report."""
    mix = lexicon.detect("Flooding near ගම්පොල, water is rising fast in the whole village now")

    assert mix.primary == "en"


# ---------------------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------------------


async def test_a_sinhala_flood_report_is_typed_without_any_model() -> None:
    """The degraded path is the ordinary path with no model attached."""
    result = await extraction.extract(SINHALA_FLOOD, call=None)

    assert result.incident_type == "FLOOD"
    assert result.provenance == "DETERMINISTIC"
    assert result.immediate_danger


async def test_a_tamil_collapse_report_is_typed_and_names_the_children() -> None:
    result = await extraction.extract(TAMIL_COLLAPSE, call=None)

    assert result.incident_type == "STRUCTURAL_COLLAPSE"
    assert "children" in result.vulnerable_present


async def test_the_keyword_path_never_produces_a_people_count() -> None:
    """Counting people is not something a keyword list can do.

    A low-confidence guess at the field that drives triage rank would be worse than the
    absence, because a number in that field is acted on and a missing one is asked about.
    """
    result = await extraction.extract(ENGLISH_TRAPPED, call=None)

    assert result.people_at_risk is None


async def test_the_keyword_path_always_asks_for_a_person() -> None:
    """Below the review threshold by design, and saying so on the record.

    Relying on the threshold alone would mean a change to it could quietly start
    auto-publishing keyword guesses into life-safety decisions.
    """
    result = await extraction.extract(SINHALA_FLOOD, call=None)

    assert result.needs_human_review
    assert result.confidence < 0.70


async def test_an_unrecognised_report_is_typed_other_and_flagged() -> None:
    result = await extraction.extract("thanks for the update, all fine here", call=None)

    assert result.incident_type == "OTHER"
    assert result.needs_human_review


# ---------------------------------------------------------------------------------------
# The people-at-risk post-check
# ---------------------------------------------------------------------------------------


def test_a_count_quoting_the_report_survives() -> None:
    extracted = extraction.ExtractedReport(
        incident_type="TRAPPED",
        people_at_risk=2,
        people_at_risk_basis="two children trapped inside",
        confidence=0.9,
        reasoning="the report says two children are trapped",
        needs_human_review=False,
    )

    checked = extraction.enforce_basis(extracted, source=ENGLISH_TRAPPED)

    assert checked.people_at_risk == 2


def test_a_count_whose_evidence_is_not_in_the_report_is_stripped() -> None:
    """The most important refusal in this agent.

    `people_at_risk` is 40% of the triage score. A number the model produced from nothing
    looks exactly like one read off the text, and it decides who a crew reaches first.
    """
    extracted = extraction.ExtractedReport(
        incident_type="TRAPPED",
        people_at_risk=40,
        people_at_risk_basis="forty people are trapped in the building",
        confidence=0.9,
        reasoning="the report describes forty people",
        needs_human_review=False,
    )

    checked = extraction.enforce_basis(extracted, source=ENGLISH_TRAPPED)

    assert checked.people_at_risk is None
    assert checked.needs_human_review
    assert "not in the report" in (checked.review_reason or "")


def test_a_basis_quoting_the_whole_report_justifies_nothing() -> None:
    """Attaching the entire text to a number is the model saying "because of what it says".

    Without this, any count could be smuggled through by quoting everything.
    """
    assert not extraction.verify_basis(ENGLISH_TRAPPED, ENGLISH_TRAPPED)


def test_an_empty_basis_fails_the_check() -> None:
    assert not extraction.verify_basis("", ENGLISH_TRAPPED)


def test_a_basis_is_matched_across_a_line_break() -> None:
    """A model quoting across two SMS segments returns the break normalised.

    Comparing raw would reject a basis that is genuinely present, which would strip good
    counts and send correct extractions to a queue.
    """
    source = "Our house collapsed\nin Gampola, two children trapped"

    assert extraction.verify_basis("collapsed in Gampola", source)


def test_a_missing_count_passes_untouched() -> None:
    """`None` is a legitimate and common answer. Requiring evidence for silence would make
    every SMS that did not count people fail."""
    extracted = extraction.ExtractedReport(
        incident_type="FLOOD",
        people_at_risk=None,
        confidence=0.9,
        reasoning="the report does not say how many",
        needs_human_review=False,
    )

    assert extraction.enforce_basis(extracted, source=SINHALA_FLOOD).people_at_risk is None


def test_an_implausibly_large_count_is_flagged_and_never_dropped() -> None:
    """Flagging is not rejection. It might be a school, and twenty seconds of a person's
    time is the whole cost of finding out."""
    extracted = extraction.ExtractedReport(
        incident_type="EVACUATION_NEEDED",
        people_at_risk=900,
        people_at_risk_basis="900",
        confidence=0.9,
        reasoning="the report says 900",
        needs_human_review=False,
    )

    flagged = extraction.flag_implausible_count(extracted)

    assert flagged.people_at_risk == 900
    assert flagged.needs_human_review


async def test_a_model_extraction_with_an_unsupported_count_loses_the_count() -> None:
    """End to end through `extract`, not just the helper."""
    answer = (
        '{"incident_type": "TRAPPED", "people_at_risk": 12, '
        '"people_at_risk_basis": "twelve people on the roof", '
        '"immediate_danger": true, "confidence": 0.9, "reasoning": "twelve on the roof"}'
    )

    result = await extraction.extract(ENGLISH_TRAPPED, call=RecordingCall(answer))

    assert result.people_at_risk is None
    assert result.needs_human_review


async def test_a_broken_model_falls_back_to_keywords_rather_than_losing_the_report() -> None:
    result = await extraction.extract(ENGLISH_TRAPPED, call=BrokenCall())

    assert result.incident_type in {"TRAPPED", "STRUCTURAL_COLLAPSE"}
    assert result.provenance == "DETERMINISTIC"


async def test_an_unparseable_model_answer_falls_back_to_keywords() -> None:
    result = await extraction.extract(SINHALA_FLOOD, call=RecordingCall("I think it's a flood!"))

    assert result.incident_type == "FLOOD"
    assert result.provenance == "DETERMINISTIC"


def test_the_incident_vocabulary_matches_the_column_that_stores_it() -> None:
    """A type this agent extracts and `incident.incident` rejects would fail at the INSERT,
    after the report was accepted and the citizen told it was received."""
    assert set(extraction.INCIDENT_TYPES) == set(SCHEMA_INCIDENT_TYPES)


def test_every_lexicon_key_is_a_type_the_database_accepts() -> None:
    assert set(lexicon.HAZARD_LEXICON) <= set(SCHEMA_INCIDENT_TYPES)


def test_an_extraction_naming_an_unknown_type_is_refused() -> None:
    with pytest.raises(ValueError, match="not an incident type"):
        extraction.ExtractedReport(
            incident_type="VOLCANO",
            confidence=0.9,
            reasoning="x",
            needs_human_review=False,
        )


# ---------------------------------------------------------------------------------------
# Geolocation
# ---------------------------------------------------------------------------------------


def _report(**kwargs) -> RawReport:
    return RawReport(report_id="rep-1", channel="APP", received_at=NOW, **kwargs)


async def test_a_good_gps_fix_is_used_as_given(gazetteer: FakeGazetteer) -> None:
    located = await geolocate.resolve(
        _report(lon=GAMPOLA_LON, lat=GAMPOLA_LAT, location_accuracy_m=20.0, location_source="gps"),
        landmarks=[],
        gazetteer=gazetteer,
    )

    assert located.has_point
    assert located.gn_division_code == DIVISION
    assert located.confidence == geolocate.CONFIDENCE_BY_SOURCE["gps_good"]


async def test_a_coarse_fix_is_used_but_carries_its_accuracy(gazetteer: FakeGazetteer) -> None:
    """A cell-derived fix five kilometres wide is worth having. Presenting it as a point
    is not, so the accuracy travels and a map can draw the circle."""
    located = await geolocate.resolve(
        _report(
            lon=GAMPOLA_LON, lat=GAMPOLA_LAT, location_accuracy_m=4000.0, location_source="cell"
        ),
        landmarks=[],
        gazetteer=gazetteer,
    )

    assert located.accuracy_m == 4000.0
    assert located.confidence == geolocate.CONFIDENCE_BY_SOURCE["gps_coarse"]


async def test_a_single_confident_landmark_becomes_a_point_with_a_wide_radius(
    gazetteer: FakeGazetteer,
) -> None:
    located = await geolocate.resolve(_report(), landmarks=["Gampola"], gazetteer=gazetteer)

    assert located.has_point
    assert located.source == "inferred"
    assert located.accuracy_m >= geolocate.LANDMARK_ACCURACY_M


async def test_an_ambiguous_landmark_produces_a_division_and_no_point() -> None:
    """Required by build file 15, and the case people get wrong.

    Sri Lanka has more than one Mahawewa. Picking one of three equally good matches is a
    guess wearing a coordinate's clothes, and a dispatcher cannot see through it.
    """
    ambiguous = FakeGazetteer(
        places={
            "mahawewa": [
                place("Mahawewa", DIVISION),
                place("Mahawewa", OTHER_DIVISION),
            ]
        }
    )

    located = await geolocate.resolve(_report(), landmarks=["Mahawewa"], gazetteer=ambiguous)

    assert located.placed
    assert not located.has_point
    assert located.gn_division_code == DIVISION


async def test_two_gazetteer_entries_in_one_division_are_not_ambiguous() -> None:
    """Two records for one village in one division are the same place, not a choice."""
    duplicated = FakeGazetteer(
        places={"gampola": [place("Gampola", DIVISION), place("Gampola Town", DIVISION)]}
    )

    located = await geolocate.resolve(_report(), landmarks=["Gampola"], gazetteer=duplicated)

    assert located.has_point


async def test_a_report_with_nothing_locatable_falls_back_to_the_senders_division() -> None:
    """Division level, no point, and the basis says where it came from - a dispatcher reads
    "the sender's registered division" differently from a landmark the report named."""
    empty = FakeGazetteer(places={})

    located = await geolocate.resolve(
        _report(sender_gn_division_code=DIVISION), landmarks=["Nowhere"], gazetteer=empty
    )

    assert located.gn_division_code == DIVISION
    assert not located.has_point
    assert "sender" in located.basis


async def test_a_report_with_nothing_at_all_is_unplaced_rather_than_guessed() -> None:
    empty = FakeGazetteer(places={})

    located = await geolocate.resolve(_report(), landmarks=[], gazetteer=empty)

    assert not located.placed
    assert located.confidence == 0.0


async def test_a_coordinate_outside_sri_lanka_is_not_used(gazetteer: FakeGazetteer) -> None:
    """Either a client bug or a report about somewhere this platform does not serve.
    Both are worth a log line rather than a silent fallback."""
    located = await geolocate.resolve(
        _report(lon=2.35, lat=48.85, location_accuracy_m=10.0, location_source="gps"),
        landmarks=["Gampola"],
        gazetteer=gazetteer,
    )

    assert located.has_point
    assert located.source == "inferred"  # fell through to the landmark
