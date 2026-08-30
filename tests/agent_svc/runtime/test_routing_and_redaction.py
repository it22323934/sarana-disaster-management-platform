"""Which model a call gets, and what leaves the country when it is traced.

Two unrelated properties in one file because both are pure functions with no I/O, and both
are the kind of rule that quietly stops holding.

**Routing** decides the model bill. Everything defaults to the cheap tier and is upgraded
deliberately; the three upgrade reasons each name a case where cheap output is measurably
worse. A test per reason, because "we upgrade when it matters" is not a specification and
the drift is invisible until an invoice arrives.

**Redaction** decides what crosses a border. Traces go to a service outside Sri Lanka and
ADR-011 is explicit that citizen data does not. The tests here are attempts to get a NIC or
a phone number past the exporter.
"""

from __future__ import annotations

import pytest

from agent_svc.runtime.models import (
    CONFIDENCE_UPGRADE_THRESHOLD,
    DEFAULT_MODELS,
    LIFE_SAFETY_FIELDS,
    Budget,
    ModelTier,
    RoutingContext,
    SpendTracker,
    explain,
    model_for,
    route,
)
from agent_svc.runtime.tracing import COORDINATE_PRECISION, redact

# --------------------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------------------


def test_the_default_is_the_cheap_tier() -> None:
    """Everything starts at VOLUME and is upgraded deliberately.

    Most nodes in this system are extraction and classification, not reasoning. Defaulting
    to a reasoning tier and downgrading the easy cases is how a platform ends up with a
    model bill somebody has to explain to a ministry.
    """
    assert route(RoutingContext(node="classify")) is ModelTier.VOLUME


def test_a_life_safety_field_is_never_extracted_cheaply() -> None:
    """Getting a people-at-risk count wrong by an order of magnitude decides how many
    vehicles are sent. That is not a cost saving."""
    for field in sorted(LIFE_SAFETY_FIELDS):
        context = RoutingContext(node="extract", extracting=(field,))
        assert route(context) is ModelTier.STANDARD, f"{field} must not run on VOLUME"


def test_code_switched_input_is_upgraded() -> None:
    """Sinhala and Tamil are low-resource languages (ADR-007), and a message that switches
    between them mid-sentence is the hardest input this platform receives — and the most
    likely to come from somebody who is not writing carefully."""
    assert route(RoutingContext(node="parse", languages=("si", "ta"))) is ModelTier.STANDARD
    # One language is the ordinary case and stays cheap.
    assert route(RoutingContext(node="parse", languages=("si", "si"))) is ModelTier.VOLUME


def test_low_prior_confidence_is_upgraded() -> None:
    """The cheap path already tried and was unsure. Asking it again changes nothing."""
    below = CONFIDENCE_UPGRADE_THRESHOLD - 0.01
    assert route(RoutingContext(node="verify", prior_confidence=below)) is ModelTier.STANDARD
    assert (
        route(RoutingContext(node="verify", prior_confidence=CONFIDENCE_UPGRADE_THRESHOLD))
        is ModelTier.VOLUME
    )


def test_escalation_is_reserved_for_two_cases() -> None:
    """Adjudication and a subject a human already rejected. Nothing else.

    The reserved list is short on purpose: an escalation tier that anything can reach is a
    default tier with an expensive name.
    """
    assert route(RoutingContext(node="supervise", adjudicating=True)) is ModelTier.ESCALATED
    assert route(RoutingContext(node="retry", previously_rejected=True)) is ModelTier.ESCALATED


def test_escalation_wins_over_the_standard_reasons() -> None:
    """A rejected life-safety extraction escalates rather than merely upgrading."""
    context = RoutingContext(node="retry", extracting=("people_at_risk",), previously_rejected=True)
    assert route(context) is ModelTier.ESCALATED


def test_every_routing_decision_can_be_explained() -> None:
    """A routing decision nobody can explain is one nobody can tune.

    This string sits next to the cost figure in the eval report, which is what makes "why
    is this agent expensive?" answerable.
    """
    cases = [
        RoutingContext(node="a"),
        RoutingContext(node="b", extracting=("severity",)),
        RoutingContext(node="c", languages=("si", "en")),
        RoutingContext(node="d", prior_confidence=0.1),
        RoutingContext(node="e", previously_rejected=True),
        RoutingContext(node="f", adjudicating=True),
    ]
    for context in cases:
        assert explain(context).strip(), f"{context.node} routes with no explanation"


def test_every_tier_maps_to_exactly_one_model() -> None:
    """One file changes when models move.

    A model string anywhere else is a second place to edit, and the one that gets missed is
    found in production.
    """
    assert set(DEFAULT_MODELS) == set(ModelTier)
    assert len(set(DEFAULT_MODELS.values())) == len(ModelTier), "two tiers share a model"

    for tier in ModelTier:
        assert model_for(tier)


def test_a_deployment_can_override_a_model_without_touching_code() -> None:
    """A model identifier is a fact about the provider's catalogue on a given day."""
    assert model_for(ModelTier.VOLUME, {ModelTier.VOLUME: "some-other-model"}) == (
        "some-other-model"
    )


def test_a_budget_of_zero_is_refused() -> None:
    """A call that cannot happen should be omitted, not configured to fail."""
    with pytest.raises(ValueError, match="budget of zero"):
        Budget(tokens=0)
    with pytest.raises(ValueError, match="budget of zero"):
        Budget(latency_ms=0)


def test_the_spend_cap_degrades_rather_than_stopping() -> None:
    """Cost must not be able to page somebody at 3 a.m. during a cyclone.

    Over the cap, every tier drops to VOLUME and the platform keeps warning people. It
    does not stop.
    """
    tracker = SpendTracker(daily_cap_usd=1.0)
    assert tracker.effective_tier(ModelTier.ESCALATED) is ModelTier.ESCALATED

    tracker.record(1.5)

    assert tracker.over_cap
    assert tracker.effective_tier(ModelTier.ESCALATED) is ModelTier.VOLUME
    assert tracker.effective_tier(ModelTier.STANDARD) is ModelTier.VOLUME


# --------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["nic", "head_nic", "msisdn", "contact_msisdn_hash", "full_name", "address", "api_key"],
)
def test_a_denied_field_is_dropped_not_masked(field: str) -> None:
    """Absence, not asterisks.

    `[REDACTED]` still tells a reader this person has a NIC on file and roughly how long
    it is. Absence tells them nothing — the same principle as the seeded households
    carrying no names at all.
    """
    cleaned = redact({field: "something sensitive", "incident_id": "abc"})

    assert field not in cleaned
    assert cleaned["incident_id"] == "abc"


def test_a_denied_field_is_caught_however_it_is_prefixed() -> None:
    """`reporter_name`, `head_nic`, `sender_msisdn` — all of them.

    Matching on the suffix means a new prefix somebody invents next month is caught
    without anybody remembering to add it.
    """
    cleaned = redact({"reporter_name": "x", "sender_msisdn": "y", "household_address": "z"})

    assert cleaned == {}


def test_coordinates_are_fuzzed_to_a_division_not_dropped() -> None:
    """A forecast is meaningless without a location, and a doorstep is a targeting list.

    Two decimal places is about a kilometre at Sri Lankan latitudes: the scale of a GN
    division.
    """
    cleaned = redact({"lat": 7.290612345, "lon": 80.633712345})

    assert cleaned["lat"] == round(7.290612345, COORDINATE_PRECISION)
    assert cleaned["lon"] == round(80.633712345, COORDINATE_PRECISION)


def test_a_nic_in_free_text_is_removed() -> None:
    """Where identifiers actually appear: in the sentence somebody typed.

    Both formats in circulation — twelve digits since 2016, nine plus V or X before that.
    Anyone holding an old card still holds it.
    """
    for nic in ("199012345678", "851234567V"):
        cleaned = redact({"body": f"my nic is {nic} and the water is rising fast here"})
        assert nic not in cleaned["body"]


def test_a_phone_number_in_free_text_is_removed() -> None:
    text = "call me on 0771234567 the road is blocked and we cannot get the children out"
    cleaned = redact({"body": text})

    assert "0771234567" not in cleaned["body"]


def test_redaction_reaches_into_nested_structures() -> None:
    """Agent state is nested, and the deny-list is worthless if it only checks the top."""
    payload = {"run": {"reports": [{"nic": "199012345678", "gn_division_code": "LK-21-01-001"}]}}

    cleaned = redact(payload)

    assert cleaned["run"]["reports"][0] == {"gn_division_code": "LK-21-01-001"}


def test_redaction_survives_a_cyclic_structure() -> None:
    """A trace exporter must not take the process down with it."""
    payload: dict[str, object] = {"a": {}}
    payload["a"] = payload  # type: ignore[index]

    assert redact(payload) is not None


def test_ordinary_fields_survive() -> None:
    """Redaction that removed everything would make tracing pointless.

    Ids, codes and decisions are what a trace is *for*.
    """
    cleaned = redact(
        {
            "incident_id": "018f-a",
            "gn_division_code": "LK-21-01-001",
            "confidence": 0.83,
            "reasoning": "two reports describe the same collapsed house",
        }
    )

    assert set(cleaned) == {"incident_id", "gn_division_code", "confidence", "reasoning"}
