"""The saturation points and incident-type weights the triage score is built from.

Shared because two services need the same numbers and neither may import the other's code:

  **incident-svc** applies them in `domain/triage.py`, the deterministic rule a dispatcher
  can check by hand.
  **agent-svc** applies them in the triage agent's extended formula, which adds terms but
  must agree with the rule on the terms they have in common.

Keeping one copy is not tidiness. Two rankings that disagree about how much a `MEDICAL`
call is worth put the same incident in two different places in two different queues, and
the dispatcher has no way to tell which one is lying.

`incident_svc.domain.triage` re-exports every name here, so the rule reads as though it
still owns them and `tests/incident/test_vocabularies.py` keeps checking the keys against
the database's CHECK vocabulary through that module.
"""

from __future__ import annotations

from typing import Final

# The count at which the people-at-risk factor saturates. Beyond this the incident is
# already the most serious kind there is, and further scaling would let one very large
# report crowd out every other.
PEOPLE_SATURATION: Final = 50

# Minutes after which the age factor saturates. Two hours: long enough that a fresh report
# does not outrank a serious older one, short enough that nothing waits a whole shift.
AGE_SATURATION_MINUTES: Final = 120

# Incident type weights, ordered by how quickly the situation kills someone unattended.
#
# The keys are exactly `incident.incident`'s CHECK vocabulary. A weight for a type the
# database rejects would be dead code; a type with no weight would silently drop to the
# mid-table default, which is the quieter and worse failure. A test asserts the two lists
# match.
INCIDENT_TYPE_WEIGHTS: Final[dict[str, float]] = {
    "MEDICAL": 1.00,
    "TRAPPED": 1.00,
    "STRUCTURAL_COLLAPSE": 0.95,
    "LANDSLIDE": 0.90,
    "FLOOD": 0.75,
    "MISSING_PERSON": 0.70,
    "EVACUATION_NEEDED": 0.65,
    "SUPPLIES_NEEDED": 0.40,
    "INFRASTRUCTURE": 0.35,
    "OTHER": 0.30,
}

# An unrecognised type sits mid-table rather than at either end. Bottom would bury a real
# emergency someone described in words we did not anticipate; top would let any unknown
# string jump the queue.
UNKNOWN_TYPE_WEIGHT: Final = 0.50
