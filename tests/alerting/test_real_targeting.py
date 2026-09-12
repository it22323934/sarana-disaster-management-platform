"""Real alert targeting: who an alert actually reaches.

Until now `_targets_for` returned one synthetic target per GN division. The fan-out, the
delivery accounting and the gaps endpoint above it were all exercised with the right
*shape* — and every number they produced was factually meaningless, because not one real
household was ever read. A district showing "1,203 unconfirmed, 865 no channel available"
was describing an area with four synthetic people in it.

It now reads `admin.household` through core-api under a credential holding
`household:contact_read` and nothing else.

The tests that matter most are the two about unreachable households and about a directory
outage, because both decide whether a coverage map tells the truth in the direction that
looks fine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest

from alerting_svc.adapters.households import (
    DirectoryUnavailable,
    HouseholdContact,
    NullDirectory,
)
from alerting_svc.api.v1.alerts import _targets_for
from sarana_shared.domain.ids import uuid7


@dataclass
class StubDirectory:
    """A directory returning whatever households the test needs."""

    contacts: list[HouseholdContact] = field(default_factory=list)
    raises: Exception | None = None
    asked: list[list[str]] = field(default_factory=list)

    async def contact(self, household_id: UUID | str) -> HouseholdContact | None:
        return None

    async def contacts_for(self, gn_division_codes: list[str]) -> list[HouseholdContact]:
        self.asked.append(list(gn_division_codes))
        if self.raises is not None:
            raise self.raises
        return self.contacts

    async def aclose(self) -> None:
        return None


def a_household(
    *,
    division: str = "LK-21-01-001",
    language: str = "si",
    reachable: bool = True,
    handset: str | None = None,
) -> HouseholdContact:
    """One household. Distinct handset unless the test deliberately shares one."""
    return HouseholdContact(
        household_id=str(uuid7()),
        recipient_ref_hash=(handset or uuid7().hex * 2) if reachable else None,
        preferred_language=language,
        gn_division_code=division,
    )


def an_alert(*codes: str) -> dict[str, Any]:
    return {"area_gn_division_ids": list(codes or ("LK-21-01-001",))}


async def test_every_household_in_the_area_becomes_a_target() -> None:
    """The point. Four households in a division are four targets, not one."""
    directory = StubDirectory(contacts=[a_household() for _ in range(4)])

    targets = await _targets_for(an_alert(), directory)

    assert len(targets) == 4
    assert len({target.target_ref_hash for target in targets}) == 4


async def test_the_whole_area_is_asked_for_at_once() -> None:
    """One bulk read, not one call per division.

    Warning a district a division at a time would be hundreds of round trips during the
    minutes when core-api is busiest and the warning is most time-critical.
    """
    directory = StubDirectory(contacts=[a_household()])

    await _targets_for(an_alert("LK-21-01-001", "LK-21-01-002", "LK-21-02-001"), directory)

    assert directory.asked == [["LK-21-01-001", "LK-21-01-002", "LK-21-02-001"]]


async def test_a_household_with_no_number_is_still_targeted() -> None:
    """The test that keeps the coverage map honest.

    An unreachable household is a delivery *gap*, not an absence. It gets a stable
    identity so the fan-out can record NO_CHANNEL against it and the gaps endpoint can
    name it as somebody who needs a vehicle with a loudhailer. Dropping it here would
    report the division as fully covered.
    """
    directory = StubDirectory(contacts=[a_household(reachable=True), a_household(reachable=False)])

    targets = await _targets_for(an_alert(), directory)

    assert len(targets) == 2
    unreachable = [t for t in targets if t.target_ref_hash.startswith("unreachable:")]
    assert len(unreachable) == 1


async def test_each_target_carries_the_households_own_language() -> None:
    """From the household record, never inferred from a name.

    Inferring language from a name is unreliable and goes wrong in exactly the communities
    most likely to be missed - which is the Ditwah failure this platform was built after.
    """
    directory = StubDirectory(
        contacts=[
            a_household(language="si"),
            a_household(language="ta"),
            a_household(language="en"),
        ]
    )

    targets = await _targets_for(an_alert(), directory)

    assert {target.preferred_language for target in targets} == {"si", "ta", "en"}


async def test_the_division_travels_with_the_target() -> None:
    """Delivery is reported per division, so the target has to carry one."""
    directory = StubDirectory(
        contacts=[
            a_household(division="LK-21-01-001"),
            a_household(division="LK-21-01-002"),
        ]
    )

    targets = await _targets_for(an_alert("LK-21-01-001", "LK-21-01-002"), directory)

    assert {target.gn_division_code for target in targets} == {
        "LK-21-01-001",
        "LK-21-01-002",
    }


async def test_a_directory_outage_stops_the_dispatch() -> None:
    """The other test that matters.

    A fan-out over the households that happened to resolve, reported as a completed
    dispatch, is worse than one that refused: the alert appears sent and the people it
    missed are invisible. `DirectoryUnavailable` propagates, and the dispatch endpoint
    turns it into a 503.
    """
    directory = StubDirectory(raises=DirectoryUnavailable("core-api is down"))

    with pytest.raises(DirectoryUnavailable):
        await _targets_for(an_alert(), directory)


async def test_an_area_that_resolves_to_nobody_produces_no_targets() -> None:
    """And says so loudly.

    Almost always a misconfigured credential or an area selection that matched nothing.
    Dispatching to nobody while reporting success is the worst available outcome, so the
    empty result is logged with the remedy.
    """
    targets = await _targets_for(an_alert(), StubDirectory(contacts=[]))

    assert targets == []


async def test_the_null_directory_reaches_nobody() -> None:
    """A deployment with no credential warns nobody, rather than warning synthetically.

    The old placeholder's failure mode: plausible-looking delivery numbers over targets
    that were never people.
    """
    targets = await _targets_for(an_alert(), NullDirectory())

    assert targets == []


async def test_two_households_sharing_a_handset_are_one_target() -> None:
    """A shared phone gets the evacuation order once.

    Common in a village, and sending the same message twice to one handset is noise at the
    moment attention is scarcest. The delivery accounting counts by contact hash anyway, so
    without this they would collapse in the figures while still costing two messages.
    """
    shared = "s" * 64
    directory = StubDirectory(contacts=[a_household(handset=shared), a_household(handset=shared)])

    targets = await _targets_for(an_alert(), directory)

    assert len(targets) == 1


async def test_unreachable_households_never_collapse_together() -> None:
    """Each is a separate person somebody has to go and find.

    They share no contact hash - they have none - so keying them on their own id is what
    keeps the gaps figure a count of people rather than a count of nulls.
    """
    directory = StubDirectory(contacts=[a_household(reachable=False) for _ in range(5)])

    targets = await _targets_for(an_alert(), directory)

    assert len(targets) == 5


async def test_two_households_in_one_division_are_two_targets() -> None:
    """The bug the placeholder had, stated directly.

    One synthetic target per division meant a division of 400 households counted as one
    person in every delivery figure the platform published.
    """
    directory = StubDirectory(contacts=[a_household(division="LK-21-01-001") for _ in range(400)])

    targets = await _targets_for(an_alert("LK-21-01-001"), directory)

    assert len(targets) == 400
