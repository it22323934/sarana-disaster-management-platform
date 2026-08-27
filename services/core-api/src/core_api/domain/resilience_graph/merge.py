"""How two observations of the same attribute are folded into one value.

Agents never write `rg_entity.attributes` directly. They append observations, and the
projection worker folds them in using the policy table below.

Every attribute the graph carries must appear in `MERGE_POLICIES`. An unregistered
attribute is refused rather than defaulted, because the failure mode of guessing is
silent: two agents disagree about how many people are displaced, one of them happens to
be written last, and the number on the operator's screen is wrong with no trace of why.
Refusing is loud, and loud is recoverable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import structlog

_log = structlog.get_logger(__name__)


class MergePolicy(StrEnum):
    """The four ways an attribute can be reconciled."""

    LATEST_WINS = "latest_wins"
    MAX = "max"
    UNION = "union"
    WEIGHTED_BY_CONFIDENCE = "weighted_by_confidence"


class UnknownAttribute(ValueError):
    """An observation named an attribute with no registered merge policy."""


@dataclass(frozen=True, slots=True)
class Observed:
    """One observation of one attribute, reduced to what merging needs."""

    value: Any
    confidence: float
    observed_at: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


def _latest_wins(existing: Observed, incoming: Observed) -> Observed:
    """The newer observation, by observation time.

    Ties go to the incoming one: re-running a projection over the same batch must be
    idempotent, and a tie means both carry the same instant anyway.
    """
    return incoming if incoming.observed_at >= existing.observed_at else existing


def _max(existing: Observed, incoming: Observed) -> Observed:
    """The larger value.

    For counts where under-reporting is the dangerous direction. Two assessors covering
    the same village separately each see part of the damage; the larger count is the
    closer one, and the smaller must not erase it.
    """
    try:
        return incoming if float(incoming.value) > float(existing.value) else existing
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"max policy needs numeric values, got {existing.value!r} and {incoming.value!r}"
        ) from error


def _union(existing: Observed, incoming: Observed) -> Observed:
    """Every distinct member of both, order preserved.

    For sets where absence from one report is not evidence of absence - a village not
    listed as cut off by one responder may simply not have been visited.
    """
    left = existing.value if isinstance(existing.value, list) else [existing.value]
    right = incoming.value if isinstance(incoming.value, list) else [incoming.value]

    merged: list[Any] = []
    seen: set[str] = set()
    for item in (*left, *right):
        marker = repr(item)
        if marker not in seen:
            seen.add(marker)
            merged.append(item)

    return Observed(
        value=merged,
        confidence=max(existing.confidence, incoming.confidence),
        observed_at=max(existing.observed_at, incoming.observed_at),
    )


def _weighted_by_confidence(existing: Observed, incoming: Observed) -> Observed:
    """A confidence-weighted mean, for estimates rather than counts.

    Used where two sources are both approximating the same continuous quantity and
    neither is authoritative. Zero total confidence falls back to the later observation,
    since a weighted mean of nothing is not defined.
    """
    try:
        left = float(existing.value)
        right = float(incoming.value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "weighted_by_confidence needs numeric values, got "
            f"{existing.value!r} and {incoming.value!r}"
        ) from error

    total = existing.confidence + incoming.confidence
    if total == 0:
        return _latest_wins(existing, incoming)

    blended = (left * existing.confidence + right * incoming.confidence) / total
    return Observed(
        value=blended,
        # The blend is at least as well supported as its better half, never more.
        confidence=max(existing.confidence, incoming.confidence),
        observed_at=max(existing.observed_at, incoming.observed_at),
    )


_MERGERS: Final[dict[MergePolicy, Callable[[Observed, Observed], Observed]]] = {
    MergePolicy.LATEST_WINS: _latest_wins,
    MergePolicy.MAX: _max,
    MergePolicy.UNION: _union,
    MergePolicy.WEIGHTED_BY_CONFIDENCE: _weighted_by_confidence,
}


# The policy per attribute. This table is the contract: adding an attribute to the graph
# means adding a line here and a test, in the same change.
MERGE_POLICIES: Final[dict[str, MergePolicy]] = {
    # Counts. Under-reporting is the dangerous direction, so the larger wins.
    "displaced_count": MergePolicy.MAX,
    "casualty_count": MergePolicy.MAX,
    "households_affected": MergePolicy.MAX,
    "shelter_occupancy": MergePolicy.MAX,
    "damaged_structures": MergePolicy.MAX,
    # Current state. The newest reading is the true one.
    "water_level_m": MergePolicy.LATEST_WINS,
    "road_status": MergePolicy.LATEST_WINS,
    "power_status": MergePolicy.LATEST_WINS,
    "cell_status": MergePolicy.LATEST_WINS,
    "shelter_status": MergePolicy.LATEST_WINS,
    "incident_status": MergePolicy.LATEST_WINS,
    "last_assessed_at": MergePolicy.LATEST_WINS,
    # Sets. Absence from one report is not evidence of absence.
    "access_routes_blocked": MergePolicy.UNION,
    "hazards_present": MergePolicy.UNION,
    "unmet_needs": MergePolicy.UNION,
    "responder_ids": MergePolicy.UNION,
    # Estimates. Two sources approximating the same continuous quantity.
    "damage_severity": MergePolicy.WEIGHTED_BY_CONFIDENCE,
    "flood_depth_estimate_m": MergePolicy.WEIGHTED_BY_CONFIDENCE,
    "population_at_risk": MergePolicy.WEIGHTED_BY_CONFIDENCE,
    "evacuation_urgency": MergePolicy.WEIGHTED_BY_CONFIDENCE,
}


def policy_for(attribute: str) -> MergePolicy:
    """The registered policy, or refuse.

    Raises:
        UnknownAttribute: if nothing is registered for this attribute.
    """
    policy = MERGE_POLICIES.get(attribute)
    if policy is None:
        raise UnknownAttribute(
            f"no merge policy registered for attribute {attribute!r}. Add one to "
            "MERGE_POLICIES with a test; an unspecified policy silently corrupts the "
            "graph rather than failing."
        )
    return policy


def merge(attribute: str, existing: Observed | None, incoming: Observed) -> Observed:
    """Fold one observation into the current value for an attribute.

    With no existing value the incoming one is taken as-is, which is what makes the
    projection safe to run from an empty graph.
    """
    policy = policy_for(attribute)
    if existing is None:
        return incoming

    merged = _MERGERS[policy](existing, incoming)
    _log.debug(
        "attribute_merged",
        attribute=attribute,
        policy=policy.value,
        kept_incoming=merged is incoming,
    )
    return merged
