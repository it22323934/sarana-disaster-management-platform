"""The intake graph end to end, and the four refusals that define it.

`test_the_same_collapsed_house_reported_twice_becomes_one_incident` is the headline case
from build file 15: a Tamil voice note and a Sinhala SMS four minutes apart about one house.
Its counterpart, `test_two_different_reports_in_one_division_stay_two_incidents`, matters
more - a duplicate costs a dispatcher ten seconds and a false merge costs somebody their
rescue.

Every test here runs with no network, no database and no model provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.types import Command

from agent_svc.agents.intake import graph as intake
from agent_svc.agents.intake.ports import Transcript
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state
from tests.agents.intake.conftest import (
    DIVISION,
    GAMPOLA_LAT,
    GAMPOLA_LON,
    NOW,
    OTHER_DIVISION,
    FakeEmbedder,
    FakeGazetteer,
    FakeIndex,
    FakeStore,
    FakeTranscriber,
    FakeTranslator,
    RecordingCall,
    neighbour,
    place,
    report_input,
)

SINHALA_COLLAPSE = "ගම්පොල නිවසක් කඩා වැටී ඇත. ළමයි ඇතුළේ. උදව් කරන්න."
TAMIL_COLLAPSE = "கம்பளையில் வீடு இடிந்தது. குழந்தைகள் உள்ளே. உதவி."


def build_graph(
    *,
    gazetteer=None,
    store=None,
    index=None,
    embedder=None,
    transcriber=None,
    translator=None,
    call=None,
):
    """Compile the graph over fakes, with the clock pinned to Ditwah's landfall night."""
    return intake.build(
        memory_checkpointer(),
        gazetteer=gazetteer or FakeGazetteer(places={"gampola": [place("Gampola")]}),
        store=store or FakeStore(),
        index=index or FakeIndex(),
        embedder=embedder,
        transcriber=transcriber,
        translator=translator,
        call=call,
        now=NOW,
        division_names={DIVISION: ["Gampola", "Deltota"]},
    )


async def run(graph, payload: dict, *, subject: str = "rep-1"):
    """Start a run and return its final values plus the config, for a resume."""
    state = initial_state(
        agent="intake",
        subject_type="report",
        subject_id=subject,
        correlation_id="test-correlation",
    )
    state["output"] = payload
    config = config_for(f"intake:report:{subject}")
    return await graph.ainvoke(state, config), config


def approve(subject: str, **extra):
    """A reviewer's decision, in the shape `assert_human_gate` requires."""
    return Command(
        resume={
            "subject_id": subject,
            "decided_by": "dmc-officer-1",
            "decided_at": datetime.now(UTC).isoformat(),
            "approved": True,
            **extra,
        }
    )


# ---------------------------------------------------------------------------------------
# The ordinary path
# ---------------------------------------------------------------------------------------


async def test_a_text_report_with_a_gps_fix_becomes_a_placed_incident() -> None:
    store = FakeStore()
    graph = build_graph(store=store)

    values, config = await run(
        graph,
        report_input(
            text=SINHALA_COLLAPSE,
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=15.0,
            source="gps",
        ),
    )

    # The keyword path always asks for a person, so the run pauses here.
    assert values["__interrupt__"]

    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["status"] == "COMPLETED"
    assert resumed["output"]["incident_type"] == "STRUCTURAL_COLLAPSE"
    assert resumed["output"]["placed"] is True
    assert resumed["output"]["has_point"] is True
    assert store.calls


async def test_the_language_is_detected_and_carried() -> None:
    graph = build_graph()

    values, _ = await run(graph, report_input(text=TAMIL_COLLAPSE))

    assert values["languages"][0] == "ta"


async def test_a_report_is_never_lost_when_nothing_can_place_it() -> None:
    """Unplaced is a real state. The report is durable and visible; it is not dispatchable
    until a person places it, and saying so beats attaching it to a division nobody has
    evidence for."""
    graph = build_graph(gazetteer=FakeGazetteer(places={}))
    store = FakeStore()
    graph = build_graph(gazetteer=FakeGazetteer(places={}), store=store)

    _, config = await run(graph, report_input(text=SINHALA_COLLAPSE))
    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["output"]["placed"] is False
    assert resumed["output"]["incident_id"] is None
    assert store.calls == []


# ---------------------------------------------------------------------------------------
# The two cases build file 15 names
# ---------------------------------------------------------------------------------------


async def test_the_same_collapsed_house_reported_twice_becomes_one_incident() -> None:
    """The headline case: a Tamil voice note and a Sinhala SMS, four minutes and 80m apart.

    The two arrive in different languages on different channels; multilingual embeddings
    are what let the recall stage see them as candidates at all.
    """
    index = FakeIndex(
        candidates=[
            neighbour(
                "rep-earlier",
                similarity=0.94,
                minutes_ago=4,
                text_original=TAMIL_COLLAPSE,
                text_en="a house collapsed in Gampola, children inside",
            )
        ]
    )
    store = FakeStore()
    graph = build_graph(store=store, index=index, embedder=FakeEmbedder())

    _, config = await run(
        graph,
        report_input(
            text=SINHALA_COLLAPSE,
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )
    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["output"]["linked_to"] == "inc-existing"
    assert resumed["output"]["created"] is False


async def test_two_different_reports_in_one_division_stay_two_incidents() -> None:
    """The case that matters more than the one above.

    Similar wording from one village during a flood is normal. Merging on it means the
    second household is never visited, and nobody notices.
    """
    index = FakeIndex(candidates=[neighbour("rep-other", similarity=0.78, incident_type="FLOOD")])
    graph = build_graph(index=index, embedder=FakeEmbedder(), call=None)

    _, config = await run(
        graph,
        report_input(
            text="ගම්පොල ගංවතුර. උදව් අවශ්‍යයි.",
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )
    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["output"]["linked_to"] is None
    assert resumed["output"]["created"] is True
    # Two incidents exist that might be one, and a person is told.
    assert resumed["output"]["flagged_pairs"] == ["rep-other"]


async def test_a_report_with_no_gps_and_an_ambiguous_landmark_has_no_point() -> None:
    """Required by build file 15. A division-level incident is valid and dispatchable."""
    ambiguous = FakeGazetteer(
        places={"mahawewa": [place("Mahawewa", DIVISION), place("Mahawewa", OTHER_DIVISION)]},
        division_at=None,
    )
    call = RecordingCall(
        '{"incident_type": "FLOOD", "people_at_risk": null, "people_at_risk_basis": "", '
        '"immediate_danger": true, "landmarks": ["Mahawewa"], "confidence": 0.9, '
        '"reasoning": "flood reported near Mahawewa"}'
    )
    store = FakeStore()
    graph = build_graph(gazetteer=ambiguous, store=store, call=call)

    _, config = await run(graph, report_input(text="Flooding near Mahawewa, help"))
    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["output"]["placed"] is True
    assert resumed["output"]["has_point"] is False
    assert store.calls[0]["lon"] is None


# ---------------------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------------------


async def test_a_voice_note_is_transcribed_with_place_name_hints() -> None:
    """The keyword hints are the single highest-leverage accuracy improvement available and
    they cost nothing."""
    transcriber = FakeTranscriber(
        transcript=Transcript(
            text_original=SINHALA_COLLAPSE,
            text_en="a house collapsed in Gampola",
            detected_language="si",
            confidence=0.92,
            provider="fake",
            model="gpt-transcribe",
        )
    )
    graph = build_graph(transcriber=transcriber)

    await run(
        graph,
        report_input(audio="s3://audio/rep-1.ogg", channel="IVR", division=DIVISION),
    )

    assert "Gampola" in transcriber.hints[0]


async def test_an_unavailable_transcriber_queues_the_audio_rather_than_losing_it() -> None:
    """A voice note that silently becomes an empty report is one nobody reads and nobody
    knows to look for. With a GPS fix it is actionable with no transcript at all."""
    graph = build_graph(transcriber=None)

    values, _ = await run(
        graph,
        report_input(
            audio="s3://audio/rep-1.ogg",
            channel="IVR",
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )

    assert values["transcript"]["status"] == intake.AUDIO_PENDING
    assert values["__interrupt__"]


async def test_a_failing_transcriber_queues_the_audio_rather_than_losing_it() -> None:
    graph = build_graph(transcriber=FakeTranscriber(fails=True))

    values, _ = await run(graph, report_input(audio="s3://audio/rep-1.ogg", channel="IVR"))

    assert values["transcript"]["status"] == intake.AUDIO_PENDING


async def test_a_low_confidence_transcription_is_never_acted_on_unread() -> None:
    """Held to a higher bar than the ordinary review threshold: a mis-heard transcript is
    not a low-confidence answer, it is a confident answer to a different question, and the
    extraction downstream cannot tell."""
    transcriber = FakeTranscriber(
        transcript=Transcript(
            text_original=SINHALA_COLLAPSE,
            text_en="a house collapsed",
            detected_language="si",
            confidence=0.60,
            provider="fake",
            model="gpt-transcribe",
        )
    )
    graph = build_graph(transcriber=transcriber)

    values, _ = await run(graph, report_input(audio="s3://audio/rep-1.ogg", channel="IVR"))

    assert values["transcript"]["low_confidence"] is True
    assert values["__interrupt__"]


async def test_the_reviewer_is_shown_the_audio_the_transcript_and_the_extraction() -> None:
    """Build file 15 asks for all three side by side, and a queue item missing any of them
    is one nobody can action."""
    transcriber = FakeTranscriber(
        transcript=Transcript(
            text_original=SINHALA_COLLAPSE,
            text_en="a house collapsed in Gampola",
            detected_language="si",
            confidence=0.55,
            provider="fake",
            model="gpt-transcribe",
        )
    )
    graph = build_graph(transcriber=transcriber)

    values, _ = await run(graph, report_input(audio="s3://audio/rep-1.ogg", channel="IVR"))
    payload = values["__interrupt__"][0].value["detail"]

    assert payload["audio_uri"] == "s3://audio/rep-1.ogg"
    assert payload["text_original"] == SINHALA_COLLAPSE
    assert payload["suggested_type"] == "STRUCTURAL_COLLAPSE"


# ---------------------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------------------


async def test_the_original_is_kept_when_a_translation_is_produced() -> None:
    """The English text is a working artefact. The original is the record."""
    graph = build_graph(translator=FakeTranslator())

    values, _ = await run(graph, report_input(text=SINHALA_COLLAPSE))

    assert values["text_original"] == SINHALA_COLLAPSE
    assert values["text_en"].startswith("[en of si]")


async def test_extraction_still_works_with_no_translator() -> None:
    """The lexicon is trilingual precisely so the pipeline does not stop when translation
    is unavailable."""
    graph = build_graph(translator=None)

    values, _ = await run(graph, report_input(text=SINHALA_COLLAPSE))

    assert values["extracted"]["incident_type"] == "STRUCTURAL_COLLAPSE"


async def test_a_failing_translator_does_not_stop_the_report() -> None:
    graph = build_graph(translator=FakeTranslator(fails=True))

    values, _ = await run(graph, report_input(text=SINHALA_COLLAPSE))

    assert values["extracted"]["incident_type"] == "STRUCTURAL_COLLAPSE"


# ---------------------------------------------------------------------------------------
# Review routing
# ---------------------------------------------------------------------------------------


async def test_a_confident_model_extraction_does_not_need_a_person() -> None:
    """The gate has to be passable, or every report queues and the queue is the bottleneck
    the agent exists to remove."""
    call = RecordingCall(
        '{"incident_type": "FLOOD", "people_at_risk": null, "people_at_risk_basis": "", '
        '"immediate_danger": true, "landmarks": [], "confidence": 0.92, '
        '"reasoning": "flood reported with water rising"}'
    )
    graph = build_graph(call=call)

    values, _ = await run(
        graph,
        report_input(
            text="Water rising fast in Gampola",
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )

    assert not values.get("__interrupt__")
    assert values["status"] == "COMPLETED"


async def test_a_plausibility_flag_routes_to_a_person_and_never_rejects() -> None:
    """The cost of ignoring a real report because it looked implausible is a death. The
    cost of a human spending twenty seconds on a false one is twenty seconds."""
    call = RecordingCall(
        '{"incident_type": "EVACUATION_NEEDED", "people_at_risk": 900, '
        '"people_at_risk_basis": "900 people", "immediate_danger": true, '
        '"landmarks": [], "confidence": 0.95, "reasoning": "900 people need evacuation"}'
    )
    store = FakeStore()
    graph = build_graph(call=call, store=store)

    values, config = await run(
        graph,
        report_input(
            text="900 people need evacuation from the school",
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )

    assert values["__interrupt__"]

    resumed = await graph.ainvoke(approve("rep-1"), config)

    # Flagged, reviewed, and still an incident. Never dropped.
    assert resumed["output"]["incident_id"] is not None


async def test_a_reviewer_can_correct_the_incident_type() -> None:
    graph = build_graph()

    _, config = await run(graph, report_input(text=SINHALA_COLLAPSE))
    resumed = await graph.ainvoke(approve("rep-1", incident_type="TRAPPED"), config)

    assert resumed["output"]["incident_type"] == "TRAPPED"
    assert resumed["output"]["provenance"] == "HUMAN"


async def test_review_runs_once_however_many_times_the_node_re_executed() -> None:
    """The interrupt node re-executes from the top on resume; `link_or_create` is downstream
    precisely so one report cannot produce two incidents."""
    store = FakeStore()
    graph = build_graph(store=store)

    _, config = await run(
        graph,
        report_input(
            text=SINHALA_COLLAPSE, lon=GAMPOLA_LON, lat=GAMPOLA_LAT, accuracy_m=20.0, source="gps"
        ),
    )
    await graph.ainvoke(approve("rep-1"), config)

    assert len(store.calls) == 1


# ---------------------------------------------------------------------------------------
# Degraded paths and identity
# ---------------------------------------------------------------------------------------


async def test_the_whole_agent_runs_with_no_provider_of_any_kind() -> None:
    """No ASR, no translator, no embedder, no model. Every test above runs this way and
    this one says so out loud."""
    graph = build_graph()

    values, config = await run(graph, report_input(text=SINHALA_COLLAPSE))
    resumed = await graph.ainvoke(approve("rep-1"), config)

    assert resumed["status"] == "COMPLETED"
    assert values["extracted"]["provenance"] == "DETERMINISTIC"


async def test_no_embedder_means_no_duplicate_search_and_no_merge() -> None:
    """Safe direction: at worst a dispatcher sees two entries and merges them by hand."""
    index = FakeIndex(candidates=[neighbour("rep-2", similarity=0.99)])
    graph = build_graph(index=index, embedder=None)

    values, _ = await run(graph, report_input(text=SINHALA_COLLAPSE))

    assert index.queried == 0
    assert values["duplicates"]["link_to_incident"] is None


async def test_a_graph_with_no_store_refuses_rather_than_processing_nothing() -> None:
    """A run that reads a citizen's report and records nothing is worse than one that
    refuses, because from the outside it is indistinguishable from a quiet night."""
    graph = intake.build(
        memory_checkpointer(),
        gazetteer=FakeGazetteer(places={"gampola": [place("Gampola")]}),
        index=FakeIndex(),
        now=NOW,
    )

    _, config = await run(
        graph,
        report_input(
            text="Flood in Gampola",
            lon=GAMPOLA_LON,
            lat=GAMPOLA_LAT,
            accuracy_m=20.0,
            source="gps",
        ),
    )

    with pytest.raises(RuntimeError, match="no store configured"):
        await graph.ainvoke(approve("rep-1"), config)


async def test_a_report_timestamped_far_in_the_future_is_flagged_not_dropped() -> None:
    """Usually a phone clock, occasionally a replayed message. Either way the report stands.

    This is also what a run against an unpinned clock does, which is why the clock is
    injected everywhere else in this file.
    """
    graph = build_graph()
    ahead = (NOW + timedelta(hours=6)).isoformat()

    payload = report_input(text="Flood in Gampola")
    payload["received_at"] = ahead

    values, _ = await run(graph, payload)
    codes = [flag["code"] for flag in values["plausibility"]["flags"]]

    assert "timestamp_in_future" in codes
    assert values["__interrupt__"]


def test_the_spec_declares_the_agent_gated_and_says_what_a_blackout_costs() -> None:
    assert intake.SPEC.gated is True
    assert intake.SPEC.subject_type == "report"
    assert "keyword" in intake.SPEC.degraded_note


def test_no_summary_is_written_rather_than_an_unreviewed_one() -> None:
    """A summary is citizen-facing text, and the platform's rule is that no citizen-facing
    record exists in fewer than three languages. The alternatives were model prose nobody
    reviewed, or one language copied into three fields and labelled as three."""
    assert intake.SUMMARY_NOT_WRITTEN is None
