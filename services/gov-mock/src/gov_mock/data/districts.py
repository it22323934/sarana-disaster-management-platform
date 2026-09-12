"""The 25 districts, as this mock holds them.

Deliberately its own copy rather than an import from `tools/seed`. A real government
system keeps its own administrative register; a mock that shares SARANA's would hide
exactly the class of bug this service exists to surface — the two disagreeing about what a
division is called or where it is.

`tests/gov_mock/test_districts_agree.py` asserts the two copies match. That is the right
shape: independent registers, checked against each other, rather than one register
pretending to be two.

Codes, names and administrative centres are real. Everything generated *from* them —
rainfall, shelters, households, officers — is synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sarana_shared.domain.admin import district_of


@dataclass(frozen=True, slots=True)
class District:
    """One district: official code, official name, and its administrative centre."""

    code: str
    province_code: str
    si: str
    ta: str
    en: str
    lon: float
    lat: float

    @property
    def is_coastal(self) -> bool:
        """Whether the district has a coastline.

        Drives storm surge, cyclone exposure and the shape of the rainfall curve. Held as
        a set of codes below rather than derived from geometry, because a rectangle around
        a centroid says nothing true about a coastline.
        """
        return self.code in COASTAL_DISTRICTS


# The twenty-five districts, with official codes and real administrative centres.
DISTRICTS: Final[tuple[District, ...]] = (
    District("LK-11", "LK-P01", "කොළඹ", "கொழும்பு", "Colombo", 79.8612, 6.9271),
    District("LK-12", "LK-P01", "ගම්පහ", "கம்பஹா", "Gampaha", 79.9990, 7.0897),
    District("LK-13", "LK-P01", "කළුතර", "களுத்துறை", "Kalutara", 79.9607, 6.5854),
    District("LK-21", "LK-P02", "මහනුවර", "கண்டி", "Kandy", 80.6337, 7.2906),
    District("LK-22", "LK-P02", "මාතලේ", "மாத்தளை", "Matale", 80.6234, 7.4675),
    District("LK-23", "LK-P02", "නුවරඑළිය", "நுவரெலியா", "Nuwara Eliya", 80.7891, 6.9497),
    District("LK-31", "LK-P03", "ගාල්ල", "காலி", "Galle", 80.2210, 6.0535),
    District("LK-32", "LK-P03", "මාතර", "மாத்தறை", "Matara", 80.5353, 5.9549),
    District("LK-33", "LK-P03", "හම්බන්තොට", "அம்பாந்தோட்டை", "Hambantota", 81.1185, 6.1241),
    District("LK-41", "LK-P04", "යාපනය", "யாழ்ப்பாணம்", "Jaffna", 80.0255, 9.6615),
    District("LK-42", "LK-P04", "කිලිනොච්චිය", "கிளிநொச்சி", "Kilinochchi", 80.4037, 9.3803),
    District("LK-43", "LK-P04", "මන්නාරම", "மன்னார்", "Mannar", 79.9045, 8.9810),
    District("LK-44", "LK-P04", "වවුනියාව", "வவுனியா", "Vavuniya", 80.4982, 8.7514),
    District("LK-45", "LK-P04", "මුලතිව්", "முல்லைத்தீவு", "Mullaitivu", 80.8142, 9.2671),
    District("LK-51", "LK-P05", "මඩකලපුව", "மட்டக்களப்பு", "Batticaloa", 81.6924, 7.7170),
    District("LK-52", "LK-P05", "අම්පාර", "அம்பாறை", "Ampara", 81.6747, 7.2911),
    District("LK-53", "LK-P05", "ත්‍රිකුණාමලය", "திருகோணமலை", "Trincomalee", 81.2335, 8.5874),
    District("LK-61", "LK-P06", "කුරුණෑගල", "குருணாகல்", "Kurunegala", 80.3609, 7.4818),
    District("LK-62", "LK-P06", "පුත්තලම", "புத்தளம்", "Puttalam", 79.8283, 8.0362),
    District("LK-71", "LK-P07", "අනුරාධපුර", "அனுராதபுரம்", "Anuradhapura", 80.4037, 8.3114),
    District("LK-72", "LK-P07", "පොළොන්නරුව", "பொலன்னறுவை", "Polonnaruwa", 81.0188, 7.9403),
    District("LK-81", "LK-P08", "බදුල්ල", "பதுளை", "Badulla", 81.0557, 6.9895),
    District("LK-82", "LK-P08", "මොණරාගල", "மொணராகலை", "Moneragala", 81.3487, 6.8728),
    District("LK-91", "LK-P09", "රත්නපුර", "இரத்தினபுரி", "Ratnapura", 80.4037, 6.6828),
    District("LK-92", "LK-P09", "කෑගල්ල", "கேகாலை", "Kegalle", 80.3464, 7.2513),
)

BY_CODE: Final[dict[str, District]] = {district.code: district for district in DISTRICTS}

# Districts with a coastline. Kandy, Matale, Nuwara Eliya, Kegalle, Ratnapura, Badulla,
# Moneragala, Anuradhapura, Polonnaruwa, Kilinochchi and Vavuniya are inland.
COASTAL_DISTRICTS: Final[frozenset[str]] = frozenset(
    {
        "LK-11",
        "LK-12",
        "LK-13",
        "LK-31",
        "LK-32",
        "LK-33",
        "LK-41",
        "LK-43",
        "LK-45",
        "LK-51",
        "LK-52",
        "LK-53",
        "LK-62",
    }
)

# The east coast, where Ditwah made landfall. The rainfall curve peaks here and decays
# westward across the island.
EAST_COAST_DISTRICTS: Final[frozenset[str]] = frozenset({"LK-51", "LK-52", "LK-53", "LK-45"})

# The seed generator's shape, mirrored so codes line up with what SARANA holds. A GN code
# is LK-{district}-{ds:02d}-{gn:03d} and the parent code is always a prefix of the child.
DS_PER_DISTRICT: Final = 4
GN_PER_DS: Final = 6


def district_for(code: str) -> District | None:
    """The district containing any district, DS or GN code, or None if unrecognised."""
    try:
        return BY_CODE.get(district_of(code))
    except ValueError:
        # `district_of` raises AdminCodeError (a ValueError) for a malformed code. A
        # caller passing rubbish gets None, the same as a caller passing a code for a
        # district that does not exist; neither is this module's problem to distinguish.
        return None


def ds_codes(district: District) -> list[str]:
    """The DS division codes under one district."""
    return [f"{district.code}-{index:02d}" for index in range(1, DS_PER_DISTRICT + 1)]


def gn_codes(district: District) -> list[str]:
    """Every GN division code under one district, in order."""
    return [
        f"{ds_code}-{gn_index:03d}"
        for ds_code in ds_codes(district)
        for gn_index in range(1, GN_PER_DS + 1)
    ]


def all_gn_codes() -> list[str]:
    """Every GN division code in the country, as this mock understands it."""
    return [code for district in DISTRICTS for code in gn_codes(district)]
