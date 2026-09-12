"""Each detector on its own, and the graph that suppresses most of what they find.

`confirmation_gap` is the one to read first. It is the most valuable detector and the most
easily misread: a division at 40% confirmation and 35% cell coverage is a coverage problem,
and firing on it would flag the least-connected divisions in the country for being least
connected — which is both wrong and exactly backwards, since those places are already the
worst served.
"""

from __future__ import annotations

from agent_svc.agents.ledger_anomaly import aggregation, detectors, normalisation
from agent_svc.agents.ledger_anomaly import graph as anomaly
from agent_svc.runtime.checkpoint import config_for, memory_checkpointer
from agent_svc.runtime.state import initial_state
from ledger_svc.repo.base import ANOMALY_SUBJECTS as SCHEMA_SUBJECTS
from ledger_svc.repo.base import DAMAGE_CATEGORIES as SCHEMA_CATEGORIES
from tests.agents.ledger_anomaly.conftest import (
    GOOD_CONTEXT,
    MILD,
    NOW,
    SEVERE,
    BrokenCall,
    FakeAssessments,
    FakeExposure,
    FakeFlagStore,
    RecordingCall,
    context,
    division,
)


def profile_for(rows, divisions):
    return normalisation.build_profiles(rows, divisions)[0]


# ---------------------------------------------------------------------------------------
# confirmation_gap: the coverage join
# ---------------------------------------------------------------------------------------


def test_confirmation_gap_does_not_fire_in_a_low_coverage_division() -> None:
    """Required by build file 17, and the most important detector test.

    Those households were never reachable to confirm anything. Flagging the division would
    flag it for having no signal.
    """
    rows = division(SEVERE, count=20, confirmed_share=0.3)
    divisions = {SEVERE: context(SEVERE, impact_class=2, coverage=35.0)}

    assert detectors.confirmation_gap(profile_for(rows, divisions)) is None


def test_confirmation_gap_fires_where_there_is_coverage_to_confirm_from() -> None:
    """The other half: at 95% coverage a 30% confirmation rate is a question worth asking."""
    rows = division(SEVERE, count=20, confirmed_share=0.3)
    divisions = {SEVERE: context(SEVERE, impact_class=2, coverage=95.0)}

    signal = detectors.confirmation_gap(profile_for(rows, divisions))

    assert signal is not None
    assert any("coverage" in item.lower() for item in signal.ruled_out)


def test_unknown_coverage_suppresses_rather_than_assuming_it_is_good() -> None:
    """An unknown is not a green light."""
    rows = division(SEVERE, count=20, confirmed_share=0.3)
    divisions = {SEVERE: context(SEVERE, impact_class=2, coverage=None)}

    assert detectors.confirmation_gap(profile_for(rows, divisions)) is None


def test_a_high_confirmation_rate_never_fires() -> None:
    rows = division(SEVERE, count=20, confirmed_share=0.95)
    divisions = {SEVERE: context(SEVERE, impact_class=2, coverage=95.0)}

    assert detectors.confirmation_gap(profile_for(rows, divisions)) is None


def test_a_division_nobody_has_asked_yet_is_not_a_gap() -> None:
    """`None` and zero are different answers: confirmation not started and everybody saying
    no look identical in a bare ratio and mean opposite things."""
    rows = division(SEVERE, count=20, confirmed_share=None)
    divisions = {SEVERE: context(SEVERE, impact_class=2, coverage=95.0)}

    assert detectors.confirmation_gap(profile_for(rows, divisions)) is None


# ---------------------------------------------------------------------------------------
# The other detectors
# ---------------------------------------------------------------------------------------


def test_temporal_burst_fires_and_names_the_survey_team_first() -> None:
    """The innocent explanation is the ordinary cause, so it leads."""
    rows = division(MILD, count=40, burst=True)
    divisions = {MILD: context(MILD, impact_class=1, households=100)}

    signal = detectors.temporal_burst(profile_for(rows, divisions))

    assert signal is not None
    assert "survey team" in signal.ruled_out[0]


def test_duplicate_household_ignores_a_legitimate_multi_category_claim() -> None:
    """A household that lost its house, its tools and its livestock has three claims and
    should. Only repeats within one category count."""
    rows = division(SEVERE, count=20, total_loss_share=0.5)
    divisions = {SEVERE: context(SEVERE, impact_class=3)}

    assert detectors.duplicate_household(profile_for(rows, divisions)) is None


def test_duplicate_household_fires_on_a_repeat_within_one_category() -> None:
    rows = division(SEVERE, count=10, household_prefix="shared") + division(
        SEVERE, count=10, household_prefix="shared"
    )
    divisions = {SEVERE: context(SEVERE, impact_class=3)}

    signal = detectors.duplicate_household(profile_for(rows, divisions))

    assert signal is not None


def test_evidence_reuse_tolerates_a_shared_wall_but_not_a_shared_album() -> None:
    """Two or three assessments sharing an image is a building. Four is a question."""
    shared = division(SEVERE, count=3, evidence=("phash-1",))
    divisions = {SEVERE: context(SEVERE, impact_class=3)}
    few = normalisation.build_profiles(shared + division(SEVERE, count=10), divisions)[0]

    assert detectors.evidence_reuse(few) is None

    many = normalisation.build_profiles(
        division(SEVERE, count=12, evidence=("phash-1",)), divisions
    )[0]

    assert detectors.evidence_reuse(many) is not None


def test_geo_implausible_needs_a_share_not_a_single_bad_fix() -> None:
    """One bad fix is a bad fix."""
    divisions = {SEVERE: context(SEVERE, impact_class=3)}
    tight = profile_for(division(SEVERE, count=20, spread_lon=0.0), divisions)

    assert detectors.geo_implausible(tight) is None

    scattered = profile_for(division(SEVERE, count=20, spread_lon=0.02), divisions)

    assert detectors.geo_implausible(scattered) is not None


def test_geo_implausible_says_which_check_it_used() -> None:
    """A centroid comparison is weaker than a point-in-polygon test, and a reviewer should
    not be misled about the precision of the check."""
    divisions = {SEVERE: context(SEVERE, impact_class=3)}
    signal = detectors.geo_implausible(
        profile_for(division(SEVERE, count=20, spread_lon=0.02), divisions)
    )

    assert signal is not None
    assert any("point-in-polygon" in (item.note or "") for item in signal.evidence)


def test_category_drift_suppresses_itself_without_housing_data() -> None:
    """It reads the division's own housing stock, and guessing would make it the detector
    most likely to produce a false positive."""
    rows = division(SEVERE, count=20, total_loss_share=1.0)
    divisions = {SEVERE: context(SEVERE, impact_class=3, permanent_housing=None)}

    assert detectors.category_drift(profile_for(rows, divisions)) is None


def test_approval_velocity_compares_against_the_district_not_the_nation() -> None:
    """Approval speed is a function of how a district is staffed. A national comparison
    would flag a well-staffed district for working quickly."""
    rows = division(SEVERE, count=20, approval_minutes=1.0)
    divisions = {SEVERE: context(SEVERE, impact_class=3)}

    signal = detectors.approval_velocity(profile_for(rows, divisions), district_median=120.0)

    assert signal is not None
    assert any("own median" in (item.note or "") for item in signal.evidence)


def test_approval_velocity_names_the_directive_first() -> None:
    """A district secretary ordering a batch approved at speed is a legitimate act."""
    rows = division(SEVERE, count=20, approval_minutes=1.0)
    divisions = {SEVERE: context(SEVERE, impact_class=3)}

    signal = detectors.approval_velocity(profile_for(rows, divisions), district_median=120.0)

    assert signal is not None
    assert "directive" in signal.ruled_out[0]


def test_every_signal_names_what_it_ruled_out() -> None:
    """Build file 17: a flag that does not show what was ruled out is not actionable and
    gets suppressed. Asserted across every detector rather than one at a time."""
    rows = division(MILD, count=40, total_loss_share=0.9, burst=True, confirmed_share=0.2)
    divisions = {MILD: context(MILD, impact_class=1, coverage=95.0, households=100)}

    signals = detectors.run_all(normalisation.build_profiles(rows, divisions))

    assert signals
    assert all(signal.ruled_out for signal in signals)
    assert all(signal.actionable for signal in signals)


# ---------------------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------------------


def test_the_subject_vocabulary_matches_the_column() -> None:
    from agent_svc.agents.ledger_anomaly.ports import ANOMALY_SUBJECTS

    assert set(ANOMALY_SUBJECTS) == set(SCHEMA_SUBJECTS)


def test_the_damage_categories_match_the_column() -> None:
    from agent_svc.agents.ledger_anomaly.ports import DAMAGE_CATEGORIES

    assert set(DAMAGE_CATEGORIES) == set(SCHEMA_CATEGORIES)


def test_flags_are_raised_against_a_division_never_a_person() -> None:
    assert anomaly.FLAG_SUBJECT == "GN_DIVISION"


# ---------------------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------------------


def build_graph(store: FakeFlagStore, *, rows=None, divisions=None, call=None):
    return anomaly.build(
        memory_checkpointer(),
        assessments=FakeAssessments(batch_rows=rows if rows is not None else []),
        exposure=FakeExposure(divisions=divisions or {}),
        store=store,
        call=call,
        now=NOW,
    )


async def run(graph, *, subject: str = "batch-1"):
    state = initial_state(
        agent="ledger_anomaly",
        subject_type="assessment_batch",
        subject_id=subject,
        correlation_id="test-correlation",
    )
    state["output"] = {"district_code": "LK-21"}
    return await graph.ainvoke(state, config_for(f"ledger_anomaly:assessment_batch:{subject}"))


async def test_a_severe_division_produces_no_flags_through_the_whole_graph(
    store: FakeFlagStore,
) -> None:
    """The normalisation property, end to end rather than at the detector."""
    graph = build_graph(
        store,
        rows=division(SEVERE, count=40, total_loss_share=0.7),
        divisions={SEVERE: context(SEVERE, impact_class=4)},
        call=RecordingCall(GOOD_CONTEXT),
    )

    values = await run(graph)

    assert values["output"]["flags_raised"] == 0
    assert store.raised == []


async def test_a_low_impact_division_with_the_same_profile_raises_a_flag(
    store: FakeFlagStore,
) -> None:
    graph = build_graph(
        store,
        rows=division(MILD, count=40, total_loss_share=0.7),
        divisions={MILD: context(MILD, impact_class=1)},
        call=RecordingCall(GOOD_CONTEXT),
    )

    values = await run(graph)

    assert values["output"]["flags_raised"] >= 1
    assert store.raised[0].subject_type == "GN_DIVISION"
    assert store.raised[0].subject_id == MILD


async def test_a_raised_flags_rationale_names_what_was_ruled_out(
    store: FakeFlagStore,
) -> None:
    graph = build_graph(
        store,
        rows=division(MILD, count=40, total_loss_share=0.7),
        divisions={MILD: context(MILD, impact_class=1)},
        call=RecordingCall(GOOD_CONTEXT),
    )

    await run(graph)
    rationale = store.raised[0].rationale

    assert rationale["innocent_explanations_ruled_out"]
    assert rationale["context"]["innocent_explanations"]


async def test_the_degraded_path_raises_at_low_priority_and_says_so(
    store: FakeFlagStore,
) -> None:
    """Build file 17 requires the marking: removing the contextualiser removes a safeguard,
    and a reviewer needs to know they are looking at a rawer signal."""
    graph = build_graph(
        store,
        rows=division(MILD, count=40, total_loss_share=0.7),
        divisions={MILD: context(MILD, impact_class=1)},
        call=BrokenCall(),
    )

    await run(graph)

    assert store.raised[0].priority == "low"
    assert store.raised[0].context_available is False


async def test_a_flag_whose_context_has_no_innocent_explanation_is_suppressed(
    store: FakeFlagStore,
) -> None:
    """Suppressed, not raised bare. A reviewer handed nothing to rule out supplies their
    own explanation, and it will be about a person."""
    empty = (
        '{"pattern_summary": "Values cluster at total loss.", "innocent_explanations": [], '
        '"what_would_resolve_it": [], "suggested_priority": "high", "confidence": 0.9}'
    )
    graph = build_graph(
        store,
        rows=division(MILD, count=40, total_loss_share=0.7),
        divisions={MILD: context(MILD, impact_class=1)},
        call=RecordingCall(empty),
    )

    values = await run(graph)

    assert store.raised == []
    assert any(item["stage"] == "no_innocent_explanation" for item in values["suppressed"])


async def test_the_aggregation_half_runs_whether_or_not_anything_is_flagged(
    store: FakeFlagStore,
) -> None:
    """These are the figures the public dashboard shows, and they must be produced whether
    or not a single flag is raised."""
    graph = build_graph(
        store,
        rows=division(SEVERE, count=40, total_loss_share=0.7, confirmed_share=0.8),
        divisions={SEVERE: context(SEVERE, impact_class=4)},
    )

    values = await run(graph)
    aggregates = values["output"]["aggregates"]

    assert values["output"]["flags_raised"] == 0
    assert aggregates["assessments"] == 40
    assert aggregates["confirmation"]["rate"] is not None
    assert aggregates["confirmation"]["asked"] == 40


async def test_the_run_output_names_no_division_at_all(store: FakeFlagStore) -> None:
    """The audit entry records that a scan happened and how much it found, not who it
    looked at."""
    graph = build_graph(
        store,
        rows=division(MILD, count=40, total_loss_share=0.7),
        divisions={MILD: context(MILD, impact_class=1)},
        call=RecordingCall(GOOD_CONTEXT),
    )

    values = await run(graph)

    assert MILD not in str(values["output"].get("reasoning", ""))


async def test_a_graph_with_no_sources_refuses_rather_than_reporting_a_clean_scan() -> None:
    """A clean scan and an unreadable ledger produce the same zero flags and mean opposite
    things."""
    import pytest

    graph = anomaly.build(memory_checkpointer())

    with pytest.raises(RuntimeError, match="assessment source"):
        await run(graph, subject="refusing")


# ---------------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------------


def test_a_small_cell_is_suppressed_but_visible() -> None:
    """A count of one household in one division for one category is a person. A suppressed
    cell reports that it exists, which is different from a zero and far different from an
    absence."""
    rollup = aggregation.summarise(division(SEVERE, count=3))
    cell = rollup.by_district[0].as_dict()

    assert cell["suppressed"] is True
    assert "count" not in cell


def test_a_large_cell_is_shown() -> None:
    rollup = aggregation.summarise(division(SEVERE, count=40))

    assert rollup.by_district[0].as_dict()["count"] == 40


def test_the_confirmation_rate_always_carries_its_denominator() -> None:
    """ "62% confirmed" is unactionable, and slightly dishonest."""
    rollup = aggregation.summarise(division(SEVERE, count=20, confirmed_share=0.5))

    assert rollup.confirmation["asked"] == 20
    assert rollup.confirmation["assessments"] == 20
    assert "coverage" in rollup.confirmation["note"]
