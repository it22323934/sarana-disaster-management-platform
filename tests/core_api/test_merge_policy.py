"""The merge policy table.

An unspecified merge policy is a silent data corruption bug: two agents disagree about how
many people are displaced, one write happens to land last, and the number on the operator's
screen is wrong with nothing in the record explaining why. So every attribute the graph
carries has a registered policy, and every policy has a test here.
"""

from __future__ import annotations

import pytest

from core_api.domain.resilience_graph.merge import (
    MERGE_POLICIES,
    MergePolicy,
    Observed,
    UnknownAttribute,
    merge,
    policy_for,
)
from core_api.workers.rg_projection import fold


def observed(value: object, *, confidence: float = 0.9, at: float = 1000.0) -> Observed:
    return Observed(value=value, confidence=confidence, observed_at=at)


def test_every_registered_attribute_has_a_known_policy() -> None:
    """The table cannot name a policy that does not exist."""
    for attribute, policy in MERGE_POLICIES.items():
        assert isinstance(policy, MergePolicy), attribute


def test_an_unregistered_attribute_is_refused_not_defaulted() -> None:
    """Guessing is the failure mode this table exists to prevent."""
    with pytest.raises(UnknownAttribute) as caught:
        policy_for("something_nobody_registered")

    assert "no merge policy registered" in str(caught.value)


def test_the_first_observation_is_taken_as_is() -> None:
    """Which is what makes the projection safe to run from an empty graph."""
    incoming = observed(5)

    assert merge("displaced_count", None, incoming) is incoming


# --------------------------------------------------------------------------------------
# The four policies
# --------------------------------------------------------------------------------------


def test_max_keeps_the_larger_count() -> None:
    """Two assessors each see part of the damage. The larger count is the closer one."""
    result = merge("displaced_count", observed(40), observed(120))

    assert result.value == 120


def test_max_does_not_let_a_smaller_later_count_erase_a_larger_one() -> None:
    """Under-reporting is the dangerous direction for a count of displaced people."""
    result = merge("displaced_count", observed(120, at=1000.0), observed(40, at=2000.0))

    assert result.value == 120, "a later, smaller count must not overwrite a larger one"


def test_latest_wins_takes_the_newer_reading() -> None:
    """For current state, the newest reading is the true one."""
    result = merge("water_level_m", observed(1.2, at=1000.0), observed(0.4, at=2000.0))

    assert result.value == 0.4


def test_latest_wins_ignores_an_older_reading_arriving_late() -> None:
    """Out-of-order delivery must not rewrite the present with the past."""
    result = merge("water_level_m", observed(0.4, at=2000.0), observed(1.2, at=1000.0))

    assert result.value == 0.4


def test_union_keeps_every_distinct_member() -> None:
    """Absence from one report is not evidence of absence."""
    result = merge(
        "access_routes_blocked",
        observed(["A9", "B12"]),
        observed(["B12", "C4"]),
    )

    assert result.value == ["A9", "B12", "C4"]


def test_union_does_not_duplicate_a_repeated_member() -> None:
    result = merge("hazards_present", observed(["flood"]), observed(["flood"]))

    assert result.value == ["flood"]


def test_weighted_by_confidence_blends_two_estimates() -> None:
    """Two sources approximating the same continuous quantity, neither authoritative."""
    result = merge(
        "damage_severity",
        observed(0.2, confidence=0.25),
        observed(1.0, confidence=0.75),
    )

    # (0.2 * 0.25 + 1.0 * 0.75) / 1.0
    assert result.value == pytest.approx(0.8)


def test_a_blend_is_never_more_confident_than_its_better_half() -> None:
    result = merge(
        "damage_severity",
        observed(0.2, confidence=0.25),
        observed(1.0, confidence=0.75),
    )

    assert result.confidence == pytest.approx(0.75)


def test_weighted_falls_back_to_latest_when_nothing_is_confident() -> None:
    """A weighted mean of zero total confidence is not defined."""
    result = merge(
        "damage_severity",
        observed(0.2, confidence=0.0, at=1000.0),
        observed(0.9, confidence=0.0, at=2000.0),
    )

    assert result.value == 0.9


def test_max_refuses_values_it_cannot_compare() -> None:
    """A count policy handed a string is a bug in the caller, not a value to guess at."""
    with pytest.raises(ValueError, match="numeric"):
        merge("displaced_count", observed(5), observed("many"))


def test_confidence_outside_zero_to_one_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        Observed(value=1, confidence=1.4, observed_at=0.0)


# --------------------------------------------------------------------------------------
# The fold the projection worker runs
# --------------------------------------------------------------------------------------


def _observation(attribute: str, value: object, confidence: float, seconds: int) -> dict:
    from datetime import UTC, datetime

    return {
        "observation_type": attribute,
        "value": value,
        "confidence": confidence,
        "observed_at": datetime.fromtimestamp(seconds, tz=UTC),
    }


def test_two_observations_of_one_attribute_apply_the_documented_policy() -> None:
    """The case named in the build brief, end to end through the fold."""
    attributes, skipped = fold(
        [
            _observation("displaced_count", 40, 0.9, 1000),
            _observation("displaced_count", 120, 0.8, 2000),
        ]
    )

    assert attributes["displaced_count"] == 120, "displaced_count is MAX"
    assert skipped == ()


def test_the_fold_applies_a_different_policy_per_attribute() -> None:
    """One pass, several attributes, each reconciled its own way."""
    attributes, skipped = fold(
        [
            _observation("displaced_count", 40, 0.9, 1000),
            _observation("displaced_count", 10, 0.9, 3000),
            _observation("water_level_m", 1.2, 0.9, 1000),
            _observation("water_level_m", 0.3, 0.9, 3000),
            _observation("hazards_present", ["flood"], 0.9, 1000),
            _observation("hazards_present", ["landslide"], 0.9, 2000),
        ]
    )

    assert attributes["displaced_count"] == 40, "MAX ignores the smaller later value"
    assert attributes["water_level_m"] == 0.3, "LATEST_WINS takes the newer reading"
    assert attributes["hazards_present"] == ["flood", "landslide"], "UNION keeps both"
    assert skipped == ()


def test_an_unknown_attribute_is_skipped_and_named_not_silently_dropped() -> None:
    """One agent's unknown attribute must not stop the rest of a division projecting."""
    attributes, skipped = fold(
        [
            _observation("displaced_count", 40, 0.9, 1000),
            _observation("who_registered_this", "?", 0.9, 1000),
        ]
    )

    assert attributes["displaced_count"] == 40, "the known attribute still projects"
    assert skipped == ("who_registered_this",)


def test_the_fold_is_idempotent_over_the_same_observations() -> None:
    """Re-running a projection after a bad deploy must not change what the graph says."""
    observations = [
        _observation("displaced_count", 40, 0.9, 1000),
        _observation("displaced_count", 120, 0.8, 2000),
        _observation("water_level_m", 0.3, 0.9, 3000),
    ]

    first, _ = fold(observations)
    second, _ = fold(observations)

    assert first == second
