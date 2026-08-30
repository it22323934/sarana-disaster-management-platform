"""Synthetic registry data: GN officers, households, and NIC verification.

Everything here is generated. Read `gov_mock.data.names` before changing any of it — the
rules about what may be generated and what may never be presented as demographic data
apply to this whole module.

**Households are generated on demand, not held in memory.** 600 divisions with a few
hundred households each is well over a hundred thousand records, and a mock that allocates
them all at boot is a mock nobody runs on a laptop. `households_for()` is a pure function
of `(seed, gn_division_code)`, so the same division yields the same households every time
without anything being stored.

**The 8% gap is the feature.** `verify_nic` returns `NOT_FOUND` for roughly one well-formed
NIC in twelve. Real registries have gaps — a card issued and never digitised, a name
transliterated differently, a record lost. The platform must be able to take a household
through assessment and payment without a registry confirmation, because the alternative is
excluding the people whose paperwork is worst, who are reliably the people who need relief
most.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Final

from gov_mock.data.derive import bucket, falls_within, seed_for
from gov_mock.data.districts import (
    DISTRICTS,
    DS_PER_DISTRICT,
    GN_PER_DS,
    District,
    district_for,
)
from gov_mock.data.names import generate_msisdn, generate_name, generate_nic

# The two NIC formats in circulation. Old cards are still valid, so both are accepted:
# code that only parses the twelve-digit form rejects everyone issued a card before 2016.
NIC_NEW_PATTERN: Final = re.compile(r"^\d{12}$")
NIC_OLD_PATTERN: Final = re.compile(r"^\d{9}[VXvx]$")

# Share of well-formed NICs the register cannot find. Build file 11 puts it at ~8%.
NOT_FOUND_SHARE: Final = 0.08

# Households per GN division. The seed generator's range for `household_count`, so a
# division's registry size is the same order as what the platform holds for it.
HOUSEHOLDS_MIN: Final = 220
HOUSEHOLDS_MAX: Final = 700

# One page of households. Deliberately not a round number and deliberately not
# configurable: a real registry has its own page size and a caller that assumes 100 gets
# a surprise on the second page.
PAGE_SIZE: Final = 37

# Officers per division. Normally one, occasionally two during a handover, occasionally
# none — a vacant division is a real and operationally important state, because it means
# nobody is doing assessments there.
_VACANT_SHARE: Final = 0.03
_HANDOVER_SHARE: Final = 0.07

# Share of household records the register itself flags as uncertain.
_NOTE_SHARE: Final = 0.06
_REGISTRY_NOTES: Final[tuple[str, ...]] = (
    "Address unverified since the 2019 update.",
    "Household reported as split; second address pending registration.",
    "Head of household changed; update not yet confirmed by the GN officer.",
)

_STREET_KINDS: Final[tuple[str, ...]] = ("Road", "Lane", "Mawatha", "Veedhi", "Place")


@dataclass(frozen=True, slots=True)
class Officer:
    """A GN officer as the register holds them."""

    service_no: str
    name: str
    gn_division_code: str
    contact_msisdn: str
    appointed_year: int
    active: bool


@dataclass(frozen=True, slots=True)
class Household:
    """A household as the register holds it."""

    household_ref: str
    gn_division_code: str
    head_name: str
    head_nic: str
    address: str
    member_count: int
    registry_note: str | None


def _rng(seed: int, *parts: str | int) -> random.Random:
    """A generator keyed to one entity, so its record is stable across requests."""
    return random.Random(seed_for(seed, *parts))  # noqa: S311 - synthetic data, not a secret


def officers_for(gn_division_code: str, *, seed: int) -> list[Officer]:
    """The officers posted to one division. Usually one; sometimes none.

    A division with no officer is not an error and must not be smoothed over. It is the
    single most useful thing this registry can tell an operator during an event: nobody is
    assessing damage in that division, and somebody has to be sent.
    """
    district = district_for(gn_division_code)
    if district is None:
        return []

    rng = _rng(seed, "officer", gn_division_code)
    draw = rng.random()
    if draw < _VACANT_SHARE:
        return []

    count = 2 if draw < _VACANT_SHARE + _HANDOVER_SHARE else 1
    officers: list[Officer] = []
    for index in range(count):
        officers.append(
            Officer(
                service_no=f"GN{gn_division_code.replace('-', '')[2:]}{index + 1}",
                name=generate_name(district.code, rng),
                gn_division_code=gn_division_code,
                contact_msisdn=generate_msisdn(rng),
                appointed_year=rng.randrange(2005, 2025),
                # During a handover the outgoing officer is still on the register and
                # inactive. A caller that takes the first row gets the wrong person.
                active=index == 0,
            )
        )
    return officers


def officer_by_service_no(service_no: str, *, seed: int) -> Officer | None:
    """Find an officer by service number.

    Reverses the derivation rather than scanning every division: the service number
    encodes the division, so the lookup is O(1) and the register does not have to be
    materialised to answer.
    """
    # District (2) + DS (2) + GN (3) + officer index (1). The code's `LK-` prefix is not
    # carried, so this is eight digits, not nine.
    digits = service_no.removeprefix("GN")
    if len(digits) != 8 or not digits.isdigit():
        return None

    gn_code = f"LK-{digits[0:2]}-{digits[2:4]}-{digits[4:7]}"
    index = int(digits[7]) - 1
    officers = officers_for(gn_code, seed=seed)
    return officers[index] if 0 <= index < len(officers) else None


def household_count_for(gn_division_code: str, *, seed: int) -> int:
    """How many households the register holds for a division."""
    if district_for(gn_division_code) is None:
        return 0
    return _rng(seed, "hh_count", gn_division_code).randrange(HOUSEHOLDS_MIN, HOUSEHOLDS_MAX)


def _build_household(
    gn_division_code: str, index: int, district: District, *, seed: int
) -> Household:
    """One household record.

    The single place a household is built, so a lookup by reference and a page of the same
    division cannot disagree about the same family — which they would, quietly, the first
    time one of the two grew a field.
    """
    rng = _rng(seed, "hh", gn_division_code, index)
    return Household(
        household_ref=household_ref(gn_division_code, index),
        gn_division_code=gn_division_code,
        head_name=generate_name(district.code, rng),
        head_nic=generate_nic(rng, new_format=rng.random() < 0.6),
        address=(
            f"{rng.randrange(1, 400)}, {district.en} {rng.choice(_STREET_KINDS)}, {district.en}"
        ),
        member_count=rng.randrange(1, 9),
        registry_note=rng.choice(_REGISTRY_NOTES) if rng.random() < _NOTE_SHARE else None,
    )


def households_for(gn_division_code: str, *, seed: int) -> list[Household]:
    """Every household in one division. A pure function of `(seed, code)`."""
    district = district_for(gn_division_code)
    if district is None:
        return []

    total = household_count_for(gn_division_code, seed=seed)
    return [
        _build_household(gn_division_code, index, district, seed=seed)
        for index in range(1, total + 1)
    ]


def household_ref(gn_division_code: str, index: int) -> str:
    """The register's reference for one household."""
    return f"HH-{gn_division_code.replace('-', '')[2:]}-{index:04d}"


def household_by_ref(reference: str, *, seed: int) -> Household | None:
    """Find one household by reference, without materialising its neighbours."""
    parts = reference.split("-")
    if len(parts) != 3 or parts[0] != "HH" or len(parts[1]) != 7:
        return None
    digits = parts[1]
    if not digits.isdigit() or not parts[2].isdigit():
        return None

    gn_code = f"LK-{digits[0:2]}-{digits[2:4]}-{digits[4:7]}"
    index = int(parts[2])
    if index < 1 or index > household_count_for(gn_code, seed=seed):
        return None

    district = district_for(gn_code)
    if district is None:
        return None

    return _build_household(gn_code, index, district, seed=seed)


def nic_is_well_formed(nic: str) -> bool:
    """Whether a NIC matches either format in circulation."""
    candidate = nic.strip()
    return bool(NIC_NEW_PATTERN.match(candidate) or NIC_OLD_PATTERN.match(candidate))


def nic_is_on_register(nic: str) -> bool:
    """Whether the register can find a well-formed NIC.

    Derived from the number itself rather than drawn at random. A NIC that verifies once
    and fails the next time would look like a flaky registry, and a household would be
    told two different things about the same card — which is far worse than a consistent
    gap.
    """
    return not falls_within(nic, share=NOT_FOUND_SHARE, salt="hhreg-missing")


def division_for_nic(nic: str) -> str:
    """Which division a verified NIC resolves to.

    Returned only for a NIC that verifies. Never a name: a verification endpoint that
    hands back a person's details for any number presented to it is a bulk lookup facility
    with a verification label on it.
    """
    district = DISTRICTS[bucket(nic, buckets=len(DISTRICTS), salt="hhreg-district")]
    ds_index = 1 + bucket(nic, buckets=DS_PER_DISTRICT, salt="hhreg-ds")
    gn_index = 1 + bucket(nic, buckets=GN_PER_DS, salt="hhreg-gn")
    return f"{district.code}-{ds_index:02d}-{gn_index:03d}"
