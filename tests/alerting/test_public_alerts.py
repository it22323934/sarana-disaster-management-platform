"""The public alert history respects the sign-off gate.

One property matters here above everything else, and it is a safety property rather than a
privacy one: **an alert that a human has not signed off must not appear on a public page.**

The gate exists so that no life-safety message reaches the population without a named person
committing to it. A gate is only real if every surface downstream of it holds the same line —
and a public page is the most downstream surface there is. A broadcaster monitoring this feed,
or a resident refreshing it during a cyclone, would act on a draft exactly as they would act
on a dispatched warning, and neither has any way to tell the difference.

The rest of this file checks the delivery figures are published honestly: `targeted` and
`reached` together, never one without the other.
"""

from __future__ import annotations

import re

from alerting_svc.api.v1.public import PublicAlert
from alerting_svc.repo.queries import _PUBLIC_ALERTS

# Every status the schema allows, from the CHECK constraint in migration 0002.
ALL_STATUSES = ("DRAFT", "PENDING_SIGNOFF", "DISPATCHING", "DISPATCHED", "CANCELLED")

# The two the public may see, and why each one.
PUBLISHED = ("DISPATCHED", "CANCELLED")


def published_statuses() -> set[str]:
    """The statuses the query's WHERE clause admits."""
    clause = re.search(r"WHERE a\.status IN \(([^)]*)\)", _PUBLIC_ALERTS)
    assert clause is not None, "the public alert query has no status filter at all"
    return set(re.findall(r"'([A-Z_]+)'", clause.group(1)))


def test_an_unapproved_alert_is_never_published() -> None:
    """DRAFT and PENDING_SIGNOFF are excluded, and that exclusion is the whole design.

    A draft is a proposal an officer has not committed to. A pending one is sitting in front
    of a human at the second gate. Publishing either puts unapproved life-safety copy on a
    page somebody can act on, which is precisely the harm the gate exists to prevent.
    """
    admitted = published_statuses()
    assert "DRAFT" not in admitted
    assert "PENDING_SIGNOFF" not in admitted


def test_an_in_flight_dispatch_is_not_published_either() -> None:
    """DISPATCHING is excluded for a narrower reason than the gate.

    The fan-out is mid-flight, so the delivery counts would be a partial number published as
    a total - an alert would appear to have reached 12% of its targets and then quietly
    become 94% on the next revalidation, with nothing on the page saying why.
    """
    assert "DISPATCHING" not in published_statuses()


def test_a_withdrawn_alert_stays_in_the_history() -> None:
    """A history that drops its own retractions is not a history.

    An alert that went out and was cancelled is a fact about what people were told, and the
    retraction is usually the part a journalist is looking for.
    """
    assert "CANCELLED" in published_statuses()


def test_the_query_admits_exactly_the_two_intended_statuses() -> None:
    """Exhaustive, so a status added to the schema later cannot drift in unnoticed."""
    assert published_statuses() == set(PUBLISHED)
    assert set(PUBLISHED) <= set(ALL_STATUSES)


def test_the_delivery_shortfall_cannot_be_shown_without_its_denominator() -> None:
    """`targeted` and `reached` are both required fields on the response.

    An alert dispatched to 12,000 contacts and confirmed to 4,000 is the most important
    fact about that alert. `reached` alone reads as a success, so the response shape does
    not allow one without the other.
    """
    fields = PublicAlert.model_fields
    for field in ("targeted", "reached"):
        assert field in fields
        assert fields[field].is_required(), f"{field} is optional and could be omitted"


def test_only_confirmed_transports_count_as_reached() -> None:
    """`NO_CHANNEL` is not a delivery, and neither is `QUEUED`.

    A household with no contact number is targeted and unreachable - they are the people who
    need a vehicle with a loudhailer. Counting them as reached would report a division as
    covered when nobody there was told anything.
    """
    reached = re.search(r"FILTER \(WHERE r\.status IN \(([^)]*)\)\)", _PUBLIC_ALERTS)
    assert reached is not None
    statuses = set(re.findall(r"'([A-Z_]+)'", reached.group(1)))

    assert statuses == {"SENT", "DELIVERED", "READ"}
    assert "NO_CHANNEL" not in statuses
    assert "QUEUED" not in statuses
    assert "FAILED" not in statuses


def test_the_public_alert_carries_all_three_languages() -> None:
    """Trilingual or it does not ship - non-negotiable #2.

    The three text fields are the whole `LocalisedText`, not the caller's locale. The
    dashboard renders three scripts from one cached response, and a per-locale endpoint
    would be three cache entries of the same alert that could drift apart.
    """
    for field in ("headline", "description", "instruction"):
        annotation = str(PublicAlert.model_fields[field].annotation)
        assert "dict[str, str]" in annotation, f"{field} is not a trilingual mapping"


def test_the_public_alert_names_no_recipient() -> None:
    """Counts of contact hashes, never a list of who was told."""
    forbidden = {
        "targets",
        "recipients",
        "contact_hash",
        "household_id",
        "msisdn",
        "area_gn_division_ids",
    }
    assert not (set(PublicAlert.model_fields) & forbidden)
    # And the query itself never selects the division list - only its cardinality.
    assert "cardinality(a.area_gn_division_ids)" in _PUBLIC_ALERTS
    assert re.search(r"^\s+a\.area_gn_division_ids,", _PUBLIC_ALERTS, re.MULTILINE) is None
