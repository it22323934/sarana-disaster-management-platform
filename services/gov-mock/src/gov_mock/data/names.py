"""Synthetic Sri Lankan names, distributed the way the population actually is.

**Every name this module produces is invented.** The components are ordinary given names
and surnames in common use — the equivalent of "John Smith" — combined by a seeded RNG. No
output corresponds to a real person, and no real person's data was used to build it,
including from a public electoral roll.

**Why the distribution matters.** A demo where every household in Batticaloa has a Sinhala
name is wrong, and it is wrong in a way that tells Tamil and Muslim communities the system
was not built with them in mind. That is the same failure the trilingual rule exists to
prevent, and it shows up in test data long before it shows up in a UI.

**About the weights.** `COMPOSITION` holds approximate district-level population shares,
rounded from the 2012 Census of Population and Housing. They are used for one purpose:
weighting which naming convention a generated name follows. They are not demographic data,
they are not current, and nothing in this platform may present them as either — no chart,
no report, no "population by ethnicity" panel. If a real figure is ever needed, take it
from the Department of Census and Statistics, not from here.

Three naming conventions are modelled, each following its own real pattern rather than
swapping a name list under one template:

  **Sinhala** — a given name and a surname, often a place-derived one.
  **Tamil** — patronymic: the father's initial precedes the person's own name.
  **Muslim** — a religious first element (Mohamed, Fathima) before the personal name.
"""

from __future__ import annotations

import random
from enum import StrEnum
from typing import Final


class NameTradition(StrEnum):
    """Which naming convention a generated name follows.

    Named for the convention, not for the person. A name tells you what tradition it comes
    from and nothing else about who carries it, and the distinction matters here because
    this weighting must never be read back as a statement about anybody's identity.
    """

    SINHALA = "sinhala"
    TAMIL = "tamil"
    MUSLIM = "muslim"


# Approximate district shares, rounded, from the 2012 census. Read the module docstring
# before using these for anything other than weighting a name generator.
#
# Ordered (sinhala, tamil, muslim); the three sum to 1.0 with other communities folded
# into the nearest of the three, because a fourth bucket with no naming convention behind
# it would generate names from the wrong tradition and look like a bug.
COMPOSITION: Final[dict[str, tuple[float, float, float]]] = {
    "LK-11": (0.77, 0.12, 0.11),  # Colombo
    "LK-12": (0.91, 0.04, 0.05),  # Gampaha
    "LK-13": (0.87, 0.03, 0.10),  # Kalutara
    "LK-21": (0.74, 0.12, 0.14),  # Kandy
    "LK-22": (0.80, 0.09, 0.11),  # Matale
    "LK-23": (0.40, 0.53, 0.07),  # Nuwara Eliya - large Indian Tamil population
    "LK-31": (0.94, 0.01, 0.05),  # Galle
    "LK-32": (0.94, 0.01, 0.05),  # Matara
    "LK-33": (0.97, 0.01, 0.02),  # Hambantota
    "LK-41": (0.01, 0.98, 0.01),  # Jaffna
    "LK-42": (0.01, 0.96, 0.03),  # Kilinochchi
    "LK-43": (0.06, 0.81, 0.13),  # Mannar
    "LK-44": (0.10, 0.83, 0.07),  # Vavuniya
    "LK-45": (0.05, 0.92, 0.03),  # Mullaitivu
    "LK-51": (0.01, 0.72, 0.27),  # Batticaloa
    "LK-52": (0.39, 0.18, 0.43),  # Ampara - Muslim plurality
    "LK-53": (0.27, 0.31, 0.42),  # Trincomalee - close to three-way
    "LK-61": (0.92, 0.01, 0.07),  # Kurunegala
    "LK-62": (0.73, 0.07, 0.20),  # Puttalam
    "LK-71": (0.91, 0.01, 0.08),  # Anuradhapura
    "LK-72": (0.91, 0.02, 0.07),  # Polonnaruwa
    "LK-81": (0.72, 0.20, 0.08),  # Badulla
    "LK-82": (0.95, 0.02, 0.03),  # Moneragala
    "LK-91": (0.86, 0.05, 0.09),  # Ratnapura
    "LK-92": (0.86, 0.03, 0.11),  # Kegalle
}

# Common given names and surnames. Ordinary, widely-borne names chosen precisely because
# they identify nobody.
_SINHALA_GIVEN: Final[tuple[str, ...]] = (
    "Nimal",
    "Sunil",
    "Chaminda",
    "Saman",
    "Ruwan",
    "Anura",
    "Lasantha",
    "Pradeep",
    "Kumari",
    "Nilanthi",
    "Chandra",
    "Malini",
    "Dilrukshi",
    "Sandya",
    "Thilaka",
    "Iresha",
)
_SINHALA_SURNAME: Final[tuple[str, ...]] = (
    "Perera",
    "Fernando",
    "Silva",
    "Bandara",
    "Rathnayake",
    "Wickramasinghe",
    "Jayawardena",
    "Gunawardena",
    "Dissanayake",
    "Senanayake",
    "Ekanayake",
    "Herath",
    "Weerasinghe",
    "Amarasinghe",
)
_TAMIL_GIVEN: Final[tuple[str, ...]] = (
    "Selvarajah",
    "Kandasamy",
    "Thavarajah",
    "Sivakumar",
    "Rajendran",
    "Mahendran",
    "Arumugam",
    "Balasubramaniam",
    "Vasanthi",
    "Sivakami",
    "Nirmala",
    "Kalaivani",
    "Thangamma",
    "Yogeswari",
    "Puvaneswari",
    "Kamalini",
)
# The father's name supplies the initial. Tamil naming is patronymic, so this list is
# given names again rather than a separate stock of surnames.
_TAMIL_PATRONYM: Final[tuple[str, ...]] = (
    "Kanagaratnam",
    "Sundaralingam",
    "Ponnambalam",
    "Nadarajah",
    "Thurairajah",
    "Sathasivam",
    "Vairamuthu",
    "Ratnasingam",
)
_MUSLIM_GIVEN: Final[tuple[str, ...]] = (
    "Rizwan",
    "Fazil",
    "Nizam",
    "Rauf",
    "Imtiyaz",
    "Riyaz",
    "Nawaz",
    "Shafeek",
    "Nasreen",
    "Zulaiha",
    "Hasna",
    "Nazreen",
    "Rihana",
    "Sameera",
    "Farhana",
    "Rushda",
)
_MUSLIM_PREFIX_MALE: Final[tuple[str, ...]] = ("Mohamed", "Ahamed", "Abdul")
_MUSLIM_PREFIX_FEMALE: Final[tuple[str, ...]] = ("Fathima", "Nooranee")
_MUSLIM_SURNAME: Final[tuple[str, ...]] = (
    "Marikkar",
    "Cassim",
    "Hameed",
    "Jiffry",
    "Saleem",
    "Thassim",
    "Uwais",
)

# Names in the female half of each given-name tuple. The lists are ordered male-then-female
# so one index tells the generator which prefix convention applies.
_FEMALE_FROM: Final = 8


def tradition_for(district_code: str, rng: random.Random) -> NameTradition:
    """Draw a naming convention appropriate to a district.

    Falls back to an island-wide average for a district code this module does not know,
    rather than defaulting to Sinhala — a silent default to the majority is precisely the
    failure this function exists to avoid.
    """
    weights = COMPOSITION.get(district_code, (0.75, 0.15, 0.10))
    drawn = rng.random()
    if drawn < weights[0]:
        return NameTradition.SINHALA
    if drawn < weights[0] + weights[1]:
        return NameTradition.TAMIL
    return NameTradition.MUSLIM


def generate_name(district_code: str, rng: random.Random) -> str:
    """One synthetic full name, following the convention drawn for this district."""
    tradition = tradition_for(district_code, rng)

    if tradition is NameTradition.SINHALA:
        return f"{rng.choice(_SINHALA_GIVEN)} {rng.choice(_SINHALA_SURNAME)}"

    if tradition is NameTradition.TAMIL:
        # Patronymic: the father's name is carried as an initial before the person's own.
        initial = rng.choice(_TAMIL_PATRONYM)[0]
        return f"{initial}. {rng.choice(_TAMIL_GIVEN)}"

    index = rng.randrange(len(_MUSLIM_GIVEN))
    prefix = (
        rng.choice(_MUSLIM_PREFIX_FEMALE)
        if index >= _FEMALE_FROM
        else rng.choice(_MUSLIM_PREFIX_MALE)
    )
    return f"{prefix} {_MUSLIM_GIVEN[index]} {rng.choice(_MUSLIM_SURNAME)}"


def generate_nic(rng: random.Random, *, new_format: bool = True) -> str:
    """A synthetic National Identity Card number in a valid *shape*.

    Two formats are in circulation and both must be handled: twelve digits since 2016, and
    nine digits with a V or X suffix before that. Anyone holding an old card still holds
    it, so code that only parses the new format rejects a large share of the people most
    likely to need relief.

    The digits are drawn at random. They are structurally valid and semantically
    meaningless, which is the only combination that is safe to generate.
    """
    if new_format:
        year = rng.randrange(1950, 2006)
        day_of_year = rng.randrange(1, 733)  # 500 is added for women, hence the range
        serial = rng.randrange(0, 10_000)
        return f"{year:04d}{day_of_year:03d}{serial:04d}0"

    year_short = rng.randrange(50, 100)
    day_of_year = rng.randrange(1, 733)
    serial = rng.randrange(0, 10_000)
    return f"{year_short:02d}{day_of_year:03d}{serial:04d}{rng.choice('VX')}"


def generate_msisdn(rng: random.Random) -> str:
    """A synthetic Sri Lankan mobile number.

    Drawn from ranges that are structurally correct but not in service. This is a mock
    telco: nothing dials these, and a number that happened to reach a real handset would
    be a demo sending an evacuation order to a stranger.
    """
    prefix = rng.choice(("070", "071", "072", "074", "075", "076", "077", "078"))
    return f"+94{prefix[1:]}{rng.randrange(0, 10_000_000):07d}"
