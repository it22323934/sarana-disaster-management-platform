"""The alerting vocabularies, guarded against drifting from the schema.

The same class of defect that bit incident-svc: a status the domain can produce and the
database rejects is a 500 at the moment an alert is being dispatched, which is the worst
possible moment.
"""

from __future__ import annotations

from alerting_svc.adapters.channels.base import LANGUAGES_PER_CHANNEL, DeliveryStatus
from alerting_svc.domain import cap
from alerting_svc.repo.base import (
    CAP_CERTAINTIES,
    CAP_SEVERITIES,
    CAP_URGENCIES,
    DELIVERY_STATUSES,
    DISPATCH_CHANNELS,
)


def test_every_delivery_status_the_domain_produces_is_storable() -> None:
    """UNKNOWN and NO_CHANNEL are the two the shipped schema was missing.

    They are the difference between a delivery picture that can say who was not reached
    and one that cannot.
    """
    assert {status.value for status in DeliveryStatus} <= set(DELIVERY_STATUSES)


def test_every_channel_the_domain_routes_is_storable() -> None:
    assert set(LANGUAGES_PER_CHANNEL) <= set(DISPATCH_CHANNELS)


def test_every_dispatch_channel_has_a_language_capacity() -> None:
    """A channel with no capacity declared would silently send one language."""
    assert set(DISPATCH_CHANNELS) <= set(LANGUAGES_PER_CHANNEL)


def test_cap_vocabularies_match_the_schema_case_insensitively() -> None:
    """CAP writes them capitalised; the schema stores them upper-case.

    Both are correct for their own layer, so the mapping is asserted rather than assumed -
    a severity that fails to round-trip would be an alert that cannot be stored.
    """
    assert {value.upper() for value in cap.SEVERITIES} == set(CAP_SEVERITIES)
    assert {value.upper() for value in cap.URGENCIES} == set(CAP_URGENCIES)
    assert {value.upper() for value in cap.CERTAINTIES} == set(CAP_CERTAINTIES)
