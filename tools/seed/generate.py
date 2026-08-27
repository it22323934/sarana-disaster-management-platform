"""Generate the local seed data under `data/seed`.

Run:  python tools/seed/generate.py

What is real and what is not, stated plainly because a demo that quietly passes synthetic
data off as official records is worse than no demo:

  - **Provinces and districts are real.** Official codes, official names, and the real
    provincial grouping. There are 9 and 25 of them and they do not change.
  - **DS and GN divisions are synthetic.** Sri Lanka has 331 and ~14,022 of them; their
    real names and boundaries come from Survey Department data this repository does not
    ship. What is generated here keeps the real code *shape* - a parent's code is always a
    prefix of its child's, which is what row-level security tests against - and lays out
    plausible boundaries around each district's true centroid.
  - **Boundaries are rectangles.** Enough for the map to render and for point-in-polygon
    resolution to be exercised. They are not survey boundaries and must never be presented
    as such.
  - **Accounts are demo accounts** with a published password. Fine for a laptop, never for
    anything reachable from a network.

Names below district level are transliterated from the district name plus a number rather
than invented. An invented Sinhala or Tamil place name would look authoritative and be
meaningless, which is the failure mode worth avoiding in a trilingual system.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SEED_ROOT: Final = REPO_ROOT / "data" / "seed"

# The demo password for every seeded account. Published on purpose: these accounts exist
# so someone can open the console on a laptop, and a secret that ships in a repository is
# not a secret. `make seed` is refused against anything but a local database.
DEMO_PASSWORD: Final = "sarana-demo-passphrase"

DS_PER_DISTRICT: Final = 4
GN_PER_DS: Final = 6

# Roughly a kilometre at Sri Lankan latitudes. GN divisions are laid out on this grid.
GN_SIZE_DEG: Final = 0.02


@dataclass(frozen=True, slots=True)
class Province:
    code: str
    si: str
    ta: str
    en: str


@dataclass(frozen=True, slots=True)
class District:
    code: str
    province: str
    si: str
    ta: str
    en: str
    lon: float
    lat: float


# The nine provinces, with official codes.
PROVINCES: Final[tuple[Province, ...]] = (
    Province("LK-P01", "බස්නාහිර", "மேற்கு", "Western"),
    Province("LK-P02", "මධ්‍යම", "மத்திய", "Central"),
    Province("LK-P03", "දකුණු", "தெற்கு", "Southern"),
    Province("LK-P04", "උතුරු", "வடக்கு", "Northern"),
    Province("LK-P05", "නැගෙනහිර", "கிழக்கு", "Eastern"),
    Province("LK-P06", "වයඹ", "வட மேற்கு", "North Western"),
    Province("LK-P07", "උතුරු මැද", "வட மத்திய", "North Central"),
    Province("LK-P08", "ඌව", "ஊவா", "Uva"),
    Province("LK-P09", "සබරගමුව", "சப்ரகமுவ", "Sabaragamuwa"),
)

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

# Demo accounts, one per role that has a console to open.
DEMO_USERS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("operator@sarana.lk", "DMC Operator", "DMC_OPERATOR", "NATIONAL"),
    ("dispatcher@sarana.lk", "Dispatch Officer", "DISPATCHER", "NATIONAL"),
    ("gn.kandy@sarana.lk", "GN Officer - Kandy", "GN_OFFICER", "GN"),
    ("ds.kandy@sarana.lk", "DS Approver - Kandy", "DS_APPROVER", "DS"),
    ("district.kandy@sarana.lk", "District Approver - Kandy", "DISTRICT_APPROVER", "DISTRICT"),
    ("auditor@sarana.lk", "Auditor", "AUDITOR", "NATIONAL"),
    ("admin@sarana.lk", "System Administrator", "ADMIN", "NATIONAL"),
)

ROLE_LABELS: Final[dict[str, tuple[str, str, str]]] = {
    "CITIZEN": ("පුරවැසි", "குடிமகன்", "Citizen"),
    "GN_OFFICER": ("ග්‍රාම නිලධාරී", "கிராம சேவகர்", "GN Officer"),
    "DS_APPROVER": ("ප්‍රාදේශීය ලේකම්", "பிரதேச செயலர்", "DS Approver"),
    "DISTRICT_APPROVER": ("දිස්ත්‍රික් ලේකම්", "மாவட்ட செயலர்", "District Approver"),
    "DMC_OPERATOR": ("ආපදා කළමනාකරණ operator", "பேரிடர் முகாமைத்துவ operator", "DMC Operator"),
    "DISPATCHER": ("යවන්නා", "அனுப்புநர்", "Dispatcher"),
    "AUDITOR": ("විගණක", "தணிக்கையாளர்", "Auditor"),
    "ADMIN": ("පරිපාලක", "நிர்வாகி", "Administrator"),
}


def _uuid7_for(label: str) -> str:
    """A stable UUID derived from a label.

    Deterministic so re-running the generator produces the same identifiers and the seed
    stays a clean upsert rather than a second copy of everything.
    """
    import hashlib
    import uuid

    digest = hashlib.sha256(label.encode("utf-8")).digest()
    # Set the version and variant bits so it is a well-formed UUID; the ordering property
    # of uuid7 does not matter for reference data that is written once.
    raw = bytearray(digest[:16])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _name(si: str, ta: str, en: str) -> dict[str, str]:
    return {"si": si, "ta": ta, "en": en}


def _rectangle(lon: float, lat: float, width: float, height: float) -> str:
    """An axis-aligned rectangle as EWKT, ready for a geometry column."""
    west, east = lon - width / 2, lon + width / 2
    south, north = lat - height / 2, lat + height / 2
    ring = (
        f"{west} {south}, {east} {south}, {east} {north}, "
        f"{west} {north}, {west} {south}"
    )
    return f"SRID=4326;MULTIPOLYGON((({ring})))"


def build_provinces() -> list[dict[str, Any]]:
    return [
        {
            "id": _uuid7_for(f"province:{province.code}"),
            "code": province.code,
            "name": _name(province.si, province.ta, province.en),
        }
        for province in PROVINCES
    ]


def build_districts() -> list[dict[str, Any]]:
    return [
        {
            "id": _uuid7_for(f"district:{district.code}"),
            "code": district.code,
            "province_id": _uuid7_for(f"province:{district.province}"),
            "name": _name(district.si, district.ta, district.en),
        }
        for district in DISTRICTS
    ]


def build_ds_divisions() -> list[dict[str, Any]]:
    """Four per district, laid out east-west across the district centre."""
    rows: list[dict[str, Any]] = []
    for district in DISTRICTS:
        for index in range(1, DS_PER_DISTRICT + 1):
            code = f"{district.code}-{index:02d}"
            rows.append(
                {
                    "id": _uuid7_for(f"ds:{code}"),
                    "code": code,
                    "district_id": _uuid7_for(f"district:{district.code}"),
                    "name": _name(
                        f"{district.si} {index}",
                        f"{district.ta} {index}",
                        f"{district.en} {index}",
                    ),
                }
            )
    return rows


def build_gn_divisions() -> list[dict[str, Any]]:
    """Six per DS division, as a strip of adjacent rectangles.

    Adjacent on purpose: a resolver that only works on well-separated shapes has not been
    tested on the case that actually occurs, which is a household near a boundary.
    """
    rows: list[dict[str, Any]] = []
    for district in DISTRICTS:
        for ds_index in range(1, DS_PER_DISTRICT + 1):
            ds_code = f"{district.code}-{ds_index:02d}"
            # Bands are centred so that one division sits exactly on the district's own
            # centroid, rather than that point landing on a seam between two.
            #
            # ST_Contains excludes the boundary, so a centroid on a shared edge resolves
            # to nothing - and the district centroid is the first coordinate anyone tries.
            # A demo where looking up Kandy returns 404 looks like a broken resolver.
            ds_lat = district.lat + (ds_index - DS_PER_DISTRICT // 2) * GN_SIZE_DEG
            for gn_index in range(1, GN_PER_DS + 1):
                code = f"{ds_code}-{gn_index:03d}"
                gn_lon = district.lon + (gn_index - GN_PER_DS // 2) * GN_SIZE_DEG
                rows.append(
                    {
                        "id": _uuid7_for(f"gn:{code}"),
                        "code": code,
                        "ds_division_id": _uuid7_for(f"ds:{ds_code}"),
                        "name": _name(
                            f"{district.si} {ds_index}-{gn_index}",
                            f"{district.ta} {ds_index}-{gn_index}",
                            f"{district.en} {ds_index}-{gn_index}",
                        ),
                        "geom": _rectangle(gn_lon, ds_lat, GN_SIZE_DEG, GN_SIZE_DEG),
                        "population": 900 + (gn_index * 137) % 2100,
                        "household_count": 220 + (gn_index * 41) % 480,
                        "elderly_pct": round(6.0 + (gn_index * 3.7) % 12, 2),
                        "under5_pct": round(5.0 + (gn_index * 2.3) % 8, 2),
                        "landslide_zone": 1 + (ds_index + gn_index) % 4,
                        "flood_return_period_m": 5 + (gn_index * 7) % 45,
                        "road_access_class": 1 + gn_index % 4,
                        "cell_coverage_pct": round(70.0 + (gn_index * 5.1) % 30, 2),
                    }
                )
    return rows


def build_roles() -> list[dict[str, Any]]:
    return [
        {
            "id": _uuid7_for(f"role:{code}"),
            "code": code,
            "name": _name(*labels),
        }
        for code, labels in ROLE_LABELS.items()
    ]


def build_users(password_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "id": _uuid7_for(f"user:{email}"),
            "email": email,
            "password_hash": password_hash,
            "full_name": full_name,
            "status": "ACTIVE",
        }
        for email, full_name, _role, _scope in DEMO_USERS
    ]


def build_user_roles() -> list[dict[str, Any]]:
    """Assign each demo account its role at the appropriate administrative scope."""
    kandy = "LK-21"
    scopes = {
        "NATIONAL": "LK",
        "DISTRICT": kandy,
        "DS": f"{kandy}-01",
        "GN": f"{kandy}-01-001",
    }
    rows: list[dict[str, Any]] = []
    for email, _full_name, role, scope_type in DEMO_USERS:
        rows.append(
            {
                "id": _uuid7_for(f"user_role:{email}:{role}"),
                "user_id": _uuid7_for(f"user:{email}"),
                "role_id": _uuid7_for(f"role:{role}"),
                "scope_type": scope_type,
                "scope_code": scopes[scope_type],
            }
        )
    return rows


def build_households() -> list[dict[str, Any]]:
    """A handful per GN division in Kandy, with no personal data at all.

    Names and phone numbers are deliberately absent rather than faked. A seeded household
    with a plausible Sinhala name and a working-looking phone number is the kind of test
    data that ends up in a screenshot, and then in a slide.
    """
    rows: list[dict[str, Any]] = []
    district = next(d for d in DISTRICTS if d.code == "LK-21")
    for ds_index in range(1, DS_PER_DISTRICT + 1):
        for gn_index in range(1, GN_PER_DS + 1):
            gn_code = f"{district.code}-{ds_index:02d}-{gn_index:03d}"
            for member in range(1, 4):
                reference = f"HH-{district.code}-{ds_index:02d}{gn_index:02d}{member:02d}"
                rows.append(
                    {
                        "id": _uuid7_for(f"household:{reference}"),
                        "gn_division_id": _uuid7_for(f"gn:{gn_code}"),
                        "reference_code": reference,
                        "member_count": 2 + (member * 2) % 6,
                        "has_over_70": member % 3 == 0,
                        "has_under_5": member % 2 == 0,
                        "has_mobility_impairment": member % 5 == 0,
                        "preferred_language": ("si", "ta", "en")[member % 3],
                    }
                )
    return rows


MANIFEST: Final[dict[str, Any]] = {
    "order": [
        {"file": "reference/province.json", "table": "admin.province", "key": ["code"]},
        {"file": "reference/district.json", "table": "admin.district", "key": ["code"]},
        {"file": "reference/ds_division.json", "table": "admin.ds_division", "key": ["code"]},
        {"file": "reference/gn_division.json", "table": "admin.gn_division", "key": ["code"]},
        {"file": "reference/role.json", "table": "admin.role", "key": ["code"]},
        {"file": "scenario/app_user.json", "table": "admin.app_user", "key": ["email"]},
        {
            "file": "scenario/user_role.json",
            "table": "admin.user_role",
            "key": ["user_id", "role_id", "scope_code"],
        },
        {
            "file": "scenario/household.json",
            "table": "admin.household",
            "key": ["reference_code"],
        },
    ]
}


def _write(relative: str, records: list[dict[str, Any]]) -> None:
    path = SEED_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  {relative:<34} {len(records):>6} records")


def main() -> int:
    from core_api.domain.auth.password import PasswordHasherService

    print("generating seed data under data/seed")
    password_hash = PasswordHasherService.create().hash(DEMO_PASSWORD)

    _write("reference/province.json", build_provinces())
    _write("reference/district.json", build_districts())
    _write("reference/ds_division.json", build_ds_divisions())
    _write("reference/gn_division.json", build_gn_divisions())
    _write("reference/role.json", build_roles())
    _write("scenario/app_user.json", build_users(password_hash))
    _write("scenario/user_role.json", build_user_roles())
    _write("scenario/household.json", build_households())

    manifest_path = SEED_ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8")
    print(f"  {'manifest.json':<34} {len(MANIFEST['order']):>6} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
