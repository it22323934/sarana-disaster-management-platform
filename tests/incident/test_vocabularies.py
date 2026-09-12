"""The incident vocabularies, and the guard against them drifting from the schema.

This service maps free text, menu choices and API bodies onto incident types the database
constrains with a CHECK. A type this code can produce and the schema rejects is a 500 on a
citizen's SOS - which is exactly what happened during development, twice, before these
tests existed.
"""

from __future__ import annotations

import re

from incident_svc.adapters.channels import sms, ussd
from incident_svc.domain import triage
from incident_svc.repo.incidents import INCIDENT_TYPES
from incident_svc.service.intake import _public_ref

# The shape `incident.incident` enforces. A citizen is quoted this over the phone.
PUBLIC_REF = re.compile(r"^INC-[0-9]{6}-[0-9A-HJKMNP-TV-Z]{6}$")


def test_every_scored_type_is_a_type_the_database_accepts() -> None:
    """A weight for a type the schema rejects is dead code at best."""
    assert set(triage.INCIDENT_TYPE_WEIGHTS) <= set(INCIDENT_TYPES)


def test_every_type_the_database_accepts_has_a_weight() -> None:
    """A type with no weight silently takes the mid-table default.

    That is the quieter failure and the worse one: the incident is ranked, plausibly, and
    wrongly, with nothing to indicate the weight was never chosen.
    """
    assert set(INCIDENT_TYPES) <= set(triage.INCIDENT_TYPE_WEIGHTS)


def test_every_sms_keyword_maps_to_a_storable_type() -> None:
    """A keyword match that produces an unstorable type turns an SOS into a 500."""
    for incident_type in sms._KEYWORDS:
        assert incident_type in INCIDENT_TYPES, incident_type


def test_every_ussd_menu_option_maps_to_a_storable_type() -> None:
    for incident_type in ussd.MENU_TYPES:
        assert incident_type in INCIDENT_TYPES, incident_type


def test_a_public_reference_matches_the_shape_the_schema_requires() -> None:
    assert PUBLIC_REF.match(_public_ref())


def test_public_references_use_an_alphabet_with_no_ambiguous_letters() -> None:
    """It is read aloud over a radio and written on paper.

    I, L, O and U are the characters people mishear and mistranscribe, so Crockford base32
    leaves them out.
    """
    references = "".join(_public_ref().split("-")[2] for _ in range(200))

    assert not set(references) & set("ILOU")


def test_public_references_do_not_collide_across_a_burst() -> None:
    """Two incidents sharing a reference would put two emergencies on one radio call."""
    references = {_public_ref() for _ in range(500)}

    assert len(references) == 500


def test_keyword_matching_prefers_the_more_urgent_reading() -> None:
    """Real messages describe several things at once.

    "trapped on the roof, water rising" is a person trapped - the flood is why. Routing it
    as a flood report puts a rescue behind a sandbag delivery.
    """
    assert sms.detect_type("trapped on the roof water rising") == "TRAPPED"
    assert sms.detect_type("injured and the water is coming in") == "MEDICAL"
    assert sms.detect_type("water rising in the house") == "FLOOD"


def test_keywords_are_declared_most_urgent_first() -> None:
    """The order is load-bearing, so it is asserted rather than assumed."""
    order = list(sms._KEYWORDS)
    weights = [triage.type_weight(name) for name in order]

    assert weights == sorted(weights, reverse=True), (
        "keyword order drives which reading wins; declare the more urgent types first"
    )
