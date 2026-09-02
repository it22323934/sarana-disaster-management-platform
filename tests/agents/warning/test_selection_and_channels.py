"""Template selection and the channel mix.

Two claims run through this file, and both are properties of what the code does with a
model's answer rather than of what it asks the model for.

**A model cannot talk a warning down to a watch.** The severity floor is applied to its
output. A rule you ask a model to follow is a rule it follows most of the time.

**A model cannot narrow the channel mix.** It proposes additions; the deterministic matrix
decides what must go out.

The quiet-hours rule and its class 3 bypass are here too, because the bypass is what makes
the restriction safe: a rule that silenced everything at night would be a rule somebody
removed the first time it mattered.
"""

from __future__ import annotations

import pytest

from agent_svc.agents.warning import catalogue as selection
from agent_svc.agents.warning import channels as channel_rules
from agent_svc.agents.warning.ports import PARAMETER_PATTERN
from alerting_svc.domain import templates as alerting_templates
from alerting_svc.repo.base import DISPATCH_CHANNELS
from tests.agents.warning.conftest import (
    NIGHT_COLOMBO,
    NOON_COLOMBO,
    SEEDED_CATALOGUE,
    BrokenCall,
    FakeCatalogue,
    RecordingCall,
)

FACTS = selection.SelectionFacts(
    gn_division_name="Gampola",
    shelter_name="Gampola Maha Vidyalaya",
    deadline_time="18:00",
)


# ---------------------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hazard", "impact_class", "expected"),
    [
        ("FLOOD", 2, "FLOOD_WATCH"),
        ("FLOOD", 3, "FLOOD_WARNING"),
        ("FLOOD", 4, "FLOOD_EVACUATE_IMMEDIATE"),
        ("LANDSLIDE", 2, "LANDSLIDE_WATCH"),
        ("LANDSLIDE", 3, "LANDSLIDE_WARNING"),
        ("CYCLONE", 4, "CYCLONE_WARNING"),
    ],
)
async def test_the_rule_matrix_selects_a_template_without_any_model(
    hazard: str, impact_class: int, expected: str
) -> None:
    """The degraded path is the ordinary path with no model attached.

    If this breaks, the agent stops working during a provider outage - which is when a
    cyclone is most likely to have taken something else down too.
    """
    choice = await selection.select(
        hazard_type=hazard,
        impact_class=impact_class,
        catalogue=SEEDED_CATALOGUE,
        facts=FACTS,
        call=None,
    )

    assert choice.template.code == expected
    assert choice.method == "RULE_MATRIX"
    assert choice.provenance == "DETERMINISTIC"


def _with_a_second_severe_flood_template() -> list[selection.AlertTemplate]:
    """A catalogue where class 3 flood has an actual choice in it.

    The model is only asked when two or more publishable templates sit at or above the
    floor - so every test about what the model may do needs a catalogue where that is true.
    """
    return [
        *SEEDED_CATALOGUE,
        selection.AlertTemplate(
            id="tpl-FLOOD_WARNING_RIVERINE",
            code="FLOOD_WARNING_RIVERINE",
            hazard_type="FLOOD",
            severity="SEVERE",
            urgency="IMMEDIATE",
            certainty="LIKELY",
            body={"si": "[si] x", "ta": "[ta] x", "en": "[en] x"},
        ),
    ]


async def test_a_model_may_choose_a_different_template_of_equal_severity() -> None:
    """The case the model is genuinely useful for: two templates fit and one fits better."""
    choice = await selection.select(
        hazard_type="FLOOD",
        impact_class=3,
        catalogue=_with_a_second_severe_flood_template(),
        facts=FACTS,
        call=RecordingCall("FLOOD_WARNING_RIVERINE"),
    )

    assert choice.template.code == "FLOOD_WARNING_RIVERINE"
    assert choice.method == "LLM"
    assert choice.provenance == "MODEL"


async def test_no_model_is_called_when_there_is_only_one_publishable_template() -> None:
    """A token spent choosing between one option buys the answer the matrix gives for free.

    At class 4 flood there is exactly one EXTREME template, so the model is never asked -
    which is also why the severity floor below has to be tested where a choice exists.
    """
    call = RecordingCall("FLOOD_EVACUATE_IMMEDIATE")

    choice = await selection.select(
        hazard_type="FLOOD",
        impact_class=4,
        catalogue=SEEDED_CATALOGUE,
        facts=FACTS,
        call=call,
    )

    assert choice.template.code == "FLOOD_EVACUATE_IMMEDIATE"
    assert choice.method == "RULE_MATRIX"
    assert call.prompts == []


async def test_a_model_cannot_talk_a_warning_down_to_a_watch() -> None:
    """The severity floor, applied to the model's output rather than asked for in its prompt.

    If this breaks, a model that decides a district is probably fine can downgrade a
    warning, and the message that goes out tells people to monitor water levels while
    their road is going under.
    """
    choice = await selection.select(
        hazard_type="FLOOD",
        impact_class=3,
        catalogue=_with_a_second_severe_flood_template(),
        facts=FACTS,
        call=RecordingCall("FLOOD_WATCH"),
    )

    assert choice.template.code == "FLOOD_WARNING"
    assert choice.method == "RULE_MATRIX"
    assert any("discarded" in note for note in choice.notes)


async def test_a_model_answer_outside_the_catalogue_is_discarded() -> None:
    """A hallucinated template code is not a template code."""
    choice = await selection.select(
        hazard_type="FLOOD",
        impact_class=3,
        catalogue=_with_a_second_severe_flood_template(),
        facts=FACTS,
        call=RecordingCall("FLOOD_APOCALYPSE_NOW"),
    )

    assert choice.template.code == "FLOOD_WARNING"
    assert choice.method == "RULE_MATRIX"


async def test_an_unreachable_model_provider_does_not_stop_a_warning() -> None:
    choice = await selection.select(
        hazard_type="CYCLONE",
        impact_class=4,
        catalogue=SEEDED_CATALOGUE,
        facts=FACTS,
        call=BrokenCall(),
    )

    assert choice.template.code == "CYCLONE_WARNING"
    assert choice.method == "RULE_MATRIX"


async def test_an_unfillable_evacuation_template_asks_a_person_rather_than_downgrading() -> None:
    """The most important refusal in this module.

    A class 4 flood with no shelter named must not quietly become a class 3 warning. That
    message would go out, read as deliberate, and tell people to prepare when they were
    meant to leave.
    """
    with pytest.raises(selection.NoSuitableTemplate) as raised:
        await selection.select(
            hazard_type="FLOOD",
            impact_class=4,
            catalogue=SEEDED_CATALOGUE,
            facts=selection.SelectionFacts(gn_division_name="Gampola"),
            call=None,
        )

    assert "shelter_name" in str(raised.value)


async def test_a_hazard_with_no_template_asks_a_person() -> None:
    with pytest.raises(selection.NoSuitableTemplate):
        await selection.select(
            hazard_type="DROUGHT",
            impact_class=3,
            catalogue=SEEDED_CATALOGUE,
            facts=FACTS,
            call=None,
        )


async def test_a_catalogue_mid_review_asks_a_person() -> None:
    """A template only reaches PUBLISHED once two named native speakers have signed it.

    A deployment part-way through that has fewer than twelve, and the missing one is not a
    reason to send the next-best thing.
    """
    partial = FakeCatalogue(templates=[t for t in SEEDED_CATALOGUE if t.code == "FLOOD_WATCH"])

    with pytest.raises(selection.NoSuitableTemplate):
        await selection.select(
            hazard_type="FLOOD",
            impact_class=3,
            catalogue=await partial.published(),
            facts=FACTS,
            call=None,
        )


def test_a_model_cannot_supply_a_parameter_value_that_is_not_a_structured_fact() -> None:
    """Free text with a template around it is still free text.

    If this breaks, `shelter_name` can be filled with whatever a model produced, and the
    soft human gate - which exists to catch exactly that - never fires because the alert
    looks template-only.
    """
    result = selection.validate_parameters(
        {"shelter_name": "the temple on the hill", "gn_division_name": "Gampola"},
        facts={"shelter_name": "Gampola Maha Vidyalaya", "gn_division_name": "Gampola"},
        allowed=frozenset({"shelter_name", "gn_division_name"}),
    )

    assert result.accepted == {"gn_division_name": "Gampola"}
    assert "shelter_name" in result.rejected
    assert not result.clean


def test_the_parameter_pattern_matches_alerting_svc() -> None:
    """Two different parameter patterns would let this agent select a template it cannot fill.

    agent-svc does not depend on alerting-svc, so the pattern is duplicated. This is what
    stops the copies drifting.
    """
    assert PARAMETER_PATTERN.pattern == alerting_templates.PARAMETER_PATTERN.pattern


# ---------------------------------------------------------------------------------------
# Channel mix
# ---------------------------------------------------------------------------------------


def test_major_impact_uses_every_available_channel() -> None:
    plan = channel_rules.plan(impact_class=3, now=NOON_COLOMBO)

    assert set(plan.channels) == set(channel_rules.ALL_CHANNELS)
    assert not plan.deferred


def test_moderate_impact_uses_the_app_and_sms_only() -> None:
    plan = channel_rules.plan(impact_class=2, now=NOON_COLOMBO, cell_coverage_pct=90.0)

    assert set(plan.channels) == {"APP", "PUSH", "SMS"}


def test_thin_cell_coverage_weights_up_the_channels_that_do_not_need_one() -> None:
    """A division at 30% coverage is one where SMS is a partial answer by construction."""
    plan = channel_rules.plan(impact_class=2, now=NOON_COLOMBO, cell_coverage_pct=30.0)

    assert {"LORA", "RADIO", "PAPER_QR"} <= set(plan.channels)


def test_below_the_alerting_threshold_nothing_is_sent() -> None:
    plan = channel_rules.plan(impact_class=1, now=NOON_COLOMBO)

    assert not plan.sends_anything


def test_a_watch_level_alert_does_not_wake_a_district_at_two_in_the_morning() -> None:
    """The quiet-hours rule.

    If this breaks, a multi-day cyclone sends watch-level SMS at 2 a.m. every twelve hours,
    and by the third night people have stopped reading them - including the one that says
    to leave.
    """
    plan = channel_rules.plan(impact_class=2, now=NIGHT_COLOMBO, cell_coverage_pct=90.0)

    assert "SMS" not in plan.channels
    assert "SMS" in plan.deferred
    assert plan.release_at is not None


def test_quiet_hours_are_bypassed_at_major_impact() -> None:
    """The bypass is what makes the restriction safe to have at all."""
    plan = channel_rules.plan(impact_class=3, now=NIGHT_COLOMBO)

    assert "SMS" in plan.channels
    assert not plan.deferred


def test_a_deferred_message_is_released_the_next_morning() -> None:
    plan = channel_rules.plan(impact_class=2, now=NIGHT_COLOMBO, cell_coverage_pct=90.0)

    assert plan.release_at is not None
    released = plan.release_at.astimezone(channel_rules.COLOMBO)
    assert released.hour == channel_rules.QUIET_RELEASE_HOUR
    assert released > NIGHT_COLOMBO.astimezone(channel_rules.COLOMBO)


def test_the_model_can_widen_the_channel_mix_but_never_narrow_it() -> None:
    """The validator has the final say, in both directions.

    A proposal that omits SMS at class 3 must not remove it, and a proposal naming a
    transport this deployment does not have must not add it.
    """
    plan = channel_rules.plan(
        impact_class=2,
        now=NOON_COLOMBO,
        available=("SMS", "APP", "LORA"),
        cell_coverage_pct=90.0,
        proposed=("LORA", "SATELLITE_PHONE"),
    )

    assert "LORA" in plan.channels
    assert "SMS" in plan.channels
    assert "SATELLITE_PHONE" not in plan.channels
    assert plan.method == "LLM_WIDENED"


async def test_a_broken_model_proposes_nothing_rather_than_raising() -> None:
    proposed = await channel_rules.propose(
        impact_class=3,
        available=channel_rules.ALL_CHANNELS,
        cell_coverage_pct=50.0,
        call=BrokenCall(),
    )

    assert proposed == ()


def test_an_alert_over_the_target_cap_is_refused_without_an_override() -> None:
    plan = channel_rules.plan(impact_class=4, now=NOON_COLOMBO, targeted=300_000, cap=250_000)

    assert plan.exceeds_cap


def test_an_override_lets_a_genuinely_national_alert_through() -> None:
    plan = channel_rules.plan(
        impact_class=4, now=NOON_COLOMBO, targeted=300_000, cap=250_000, override_cap=True
    )

    assert not plan.exceeds_cap


def test_the_channel_vocabulary_matches_the_column_that_stores_it() -> None:
    """A channel this agent selects and `alerting.dispatch.channel` rejects fails at the
    INSERT, after the warning has already gone out."""
    assert set(channel_rules.ALL_CHANNELS) == set(DISPATCH_CHANNELS)


def test_the_target_cap_matches_alerting_svcs_own() -> None:
    """The agent refuses before it calls dispatch, so it holds its own copy of the cap.

    Two different caps would mean the agent either refuses alerts alerting-svc would have
    accepted, or builds a whole fan-out that comes back as a 409.
    """
    from alerting_svc.config import Settings

    assert Settings.model_fields["alert_target_cap"].default == channel_rules.DEFAULT_TARGET_CAP
