"""The reference taxonomies, with the trilingual labels a client renders.

`core-api` serves these from `/api/v1/meta/reference` so that every client - the ops
console, the public dashboard, both mobile apps - draws its dropdowns from one list
instead of hardcoding four copies that drift apart.

The enum *values* are owned by the service whose schema constrains them; this module holds
the canonical copy and a test asserts the two agree. The *labels* are owned here, because
a label is a presentation concern and no service should have an opinion about how its
status codes read in Tamil.

Translation status: these labels are working translations and are marked for native
review, the same standard the alert templates are held to. A status label that reads
oddly is a usability problem; the platform's rule that nothing citizen-facing ships in
fewer than three languages is what stops it becoming an access problem.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------------------
# Values. These mirror the CHECK constraints in the owning services' schemas.
# --------------------------------------------------------------------------------------

LOCALES: Final[tuple[str, ...]] = ("si", "ta", "en")

HAZARD_TYPES: Final[tuple[str, ...]] = (
    "FLOOD",
    "LANDSLIDE",
    "CYCLONE",
    "DROUGHT",
    "STORM_SURGE",
)

HAZARD_STATUSES: Final[tuple[str, ...]] = (
    "MONITORING",
    "DECLARED",
    "ACTIVE",
    "SUBSIDING",
    "CLOSED",
)

INCIDENT_STATUSES: Final[tuple[str, ...]] = (
    "REPORTED",
    "VERIFIED",
    "TRIAGED",
    "DISPATCHED",
    "IN_PROGRESS",
    "RESOLVED",
    "DUPLICATE",
    "REJECTED",
)

INTAKE_CHANNELS: Final[tuple[str, ...]] = (
    "SMS",
    "USSD",
    "VOICE",
    "APP",
    "WEB",
    "LORA",
    "FIELD_OFFICER",
    "PARTNER_API",
)

DAMAGE_CATEGORIES: Final[tuple[str, ...]] = (
    "HOUSE_FULL",
    "HOUSE_PARTIAL",
    "HOUSEHOLD_GOODS",
    "LIVELIHOOD_TOOLS",
    "CROP",
    "LIVESTOCK",
    "FISHING_GEAR",
    "DEATH",
    "INJURY",
)

ENTITLEMENT_STATUSES: Final[tuple[str, ...]] = (
    "CALCULATED",
    "AWAITING_DS",
    "AWAITING_DISTRICT",
    "APPROVED",
    "REJECTED",
    "DISBURSED",
)

PAYMENT_RAILS: Final[tuple[str, ...]] = (
    "BANK_TRANSFER",
    "MOBILE_MONEY",
    "POST_OFFICE",
    "CASH",
)

ALERT_STATUSES: Final[tuple[str, ...]] = (
    "DRAFT",
    "PENDING_SIGNOFF",
    "DISPATCHING",
    "DISPATCHED",
    "CANCELLED",
)

DISPATCH_STATUSES: Final[tuple[str, ...]] = (
    "PROPOSED",
    "AWAITING_SIGNOFF",
    "APPROVED",
    "REJECTED",
    "RELEASED",
    "COMPLETED",
)


# --------------------------------------------------------------------------------------
# Labels. si / ta / en for every value above.
# --------------------------------------------------------------------------------------

_LABELS: Final[dict[str, dict[str, dict[str, str]]]] = {
    "locales": {
        "si": {"si": "සිංහල", "ta": "சிங்களம்", "en": "Sinhala"},
        "ta": {"si": "දෙමළ", "ta": "தமிழ்", "en": "Tamil"},
        "en": {"si": "ඉංග්‍රීසි", "ta": "ஆங்கிலம்", "en": "English"},
    },
    "hazard_types": {
        "FLOOD": {"si": "ගංවතුර", "ta": "வெள்ளம்", "en": "Flood"},
        "LANDSLIDE": {"si": "නායයෑම්", "ta": "நிலச்சரிவு", "en": "Landslide"},
        "CYCLONE": {"si": "සුළිකුණාටුව", "ta": "சூறாவளி", "en": "Cyclone"},
        "DROUGHT": {"si": "නියඟය", "ta": "வறட்சி", "en": "Drought"},
        "STORM_SURGE": {"si": "කුණාටු රළ", "ta": "புயல் அலை", "en": "Storm surge"},
    },
    "hazard_statuses": {
        "MONITORING": {"si": "නිරීක්ෂණය", "ta": "கண்காணிப்பு", "en": "Monitoring"},
        "DECLARED": {"si": "ප්‍රකාශිත", "ta": "அறிவிக்கப்பட்டது", "en": "Declared"},
        "ACTIVE": {"si": "සක්‍රීය", "ta": "செயலில்", "en": "Active"},
        "SUBSIDING": {"si": "අඩුවෙමින්", "ta": "தணிகிறது", "en": "Subsiding"},
        "CLOSED": {"si": "වසා ඇත", "ta": "மூடப்பட்டது", "en": "Closed"},
    },
    "incident_statuses": {
        "REPORTED": {"si": "වාර්තා විය", "ta": "அறிவிக்கப்பட்டது", "en": "Reported"},
        "VERIFIED": {"si": "සත්‍යාපිත", "ta": "சரிபார்க்கப்பட்டது", "en": "Verified"},
        "TRIAGED": {"si": "වර්ගීකෘත", "ta": "வகைப்படுத்தப்பட்டது", "en": "Triaged"},
        "DISPATCHED": {"si": "යවන ලදී", "ta": "அனுப்பப்பட்டது", "en": "Dispatched"},
        "IN_PROGRESS": {"si": "ක්‍රියාත්මකයි", "ta": "நடைபெறுகிறது", "en": "In progress"},
        "RESOLVED": {"si": "විසඳා ඇත", "ta": "தீர்க்கப்பட்டது", "en": "Resolved"},
        "DUPLICATE": {"si": "අනුපිටපත", "ta": "நகல்", "en": "Duplicate"},
        "REJECTED": {"si": "ප්‍රතික්ෂේපිත", "ta": "நிராகரிக்கப்பட்டது", "en": "Rejected"},
    },
    "intake_channels": {
        "SMS": {"si": "කෙටි පණිවුඩ", "ta": "குறுஞ்செய்தி", "en": "SMS"},
        "USSD": {"si": "USSD", "ta": "USSD", "en": "USSD"},
        "VOICE": {"si": "හඬ ඇමතුම", "ta": "குரல் அழைப்பு", "en": "Voice call"},
        "APP": {"si": "ජංගම යෙදුම", "ta": "செயலி", "en": "Mobile app"},
        "WEB": {"si": "වෙබ්", "ta": "இணையம்", "en": "Web"},
        "LORA": {"si": "LoRa ජාලය", "ta": "LoRa வலையமைப்பு", "en": "LoRa mesh"},
        "FIELD_OFFICER": {
            "si": "ක්ෂේත්‍ර නිලධාරී",
            "ta": "கள அலுவலர்",
            "en": "Field officer",
        },
        "PARTNER_API": {
            "si": "හවුල්කරු API",
            "ta": "பங்குதாரர் API",
            "en": "Partner API",
        },
    },
    "damage_categories": {
        "HOUSE_FULL": {
            "si": "නිවස සම්පූර්ණයෙන් හානි",
            "ta": "வீடு முழுமையாக சேதம்",
            "en": "House fully damaged",
        },
        "HOUSE_PARTIAL": {
            "si": "නිවස අර්ධ වශයෙන් හානි",
            "ta": "வீடு பகுதியளவு சேதம்",
            "en": "House partially damaged",
        },
        "HOUSEHOLD_GOODS": {
            "si": "ගෘහ භාණ්ඩ",
            "ta": "வீட்டு உபகரணங்கள்",
            "en": "Household goods",
        },
        "LIVELIHOOD_TOOLS": {
            "si": "ජීවනෝපාය උපකරණ",
            "ta": "வாழ்வாதார கருவிகள்",
            "en": "Livelihood tools",
        },
        "CROP": {"si": "බෝග", "ta": "பயிர்", "en": "Crops"},
        "LIVESTOCK": {"si": "පශු සම්පත", "ta": "கால்நடை", "en": "Livestock"},
        "FISHING_GEAR": {
            "si": "ධීවර උපකරණ",
            "ta": "மீன்பிடி உபகரணங்கள்",
            "en": "Fishing gear",
        },
        "DEATH": {"si": "මරණය", "ta": "இறப்பு", "en": "Death"},
        "INJURY": {"si": "තුවාල", "ta": "காயம்", "en": "Injury"},
    },
    "entitlement_statuses": {
        "CALCULATED": {"si": "ගණනය කර ඇත", "ta": "கணக்கிடப்பட்டது", "en": "Calculated"},
        "AWAITING_DS": {
            "si": "ප්‍රාදේශීය ලේකම් අනුමැතිය බලාපොරොත්තුවෙන්",
            "ta": "பிரதேச செயலர் ஒப்புதலுக்காக",
            "en": "Awaiting DS approval",
        },
        "AWAITING_DISTRICT": {
            "si": "දිස්ත්‍රික් අනුමැතිය බලාපොරොත්තුවෙන්",
            "ta": "மாவட்ட ஒப்புதலுக்காக",
            "en": "Awaiting District approval",
        },
        "APPROVED": {"si": "අනුමතයි", "ta": "அங்கீகரிக்கப்பட்டது", "en": "Approved"},
        "REJECTED": {"si": "ප්‍රතික්ෂේපිත", "ta": "நிராகரிக்கப்பட்டது", "en": "Rejected"},
        "DISBURSED": {"si": "ගෙවා ඇත", "ta": "வழங்கப்பட்டது", "en": "Disbursed"},
    },
    "payment_rails": {
        "BANK_TRANSFER": {
            "si": "බැංකු මාරුව",
            "ta": "வங்கி பரிமாற்றம்",
            "en": "Bank transfer",
        },
        "MOBILE_MONEY": {
            "si": "ජංගම මුදල්",
            "ta": "கைபேசி பணம்",
            "en": "Mobile money",
        },
        "POST_OFFICE": {"si": "තැපැල් කාර්යාලය", "ta": "தபால் அலுவலகம்", "en": "Post office"},
        "CASH": {"si": "මුදල්", "ta": "பணம்", "en": "Cash"},
    },
    "alert_statuses": {
        "DRAFT": {"si": "කෙටුම්පත", "ta": "வரைவு", "en": "Draft"},
        "PENDING_SIGNOFF": {
            "si": "අනුමැතිය බලාපොරොත්තුවෙන්",
            "ta": "ஒப்புதலுக்காக காத்திருக்கிறது",
            "en": "Pending sign-off",
        },
        "DISPATCHING": {"si": "යවමින්", "ta": "அனுப்பப்படுகிறது", "en": "Dispatching"},
        "DISPATCHED": {"si": "යවන ලදී", "ta": "அனுப்பப்பட்டது", "en": "Dispatched"},
        "CANCELLED": {"si": "අවලංගු කර ඇත", "ta": "ரத்து செய்யப்பட்டது", "en": "Cancelled"},
    },
    "dispatch_statuses": {
        "PROPOSED": {"si": "යෝජිත", "ta": "முன்மொழியப்பட்டது", "en": "Proposed"},
        "AWAITING_SIGNOFF": {
            "si": "අනුමැතිය බලාපොරොත්තුවෙන්",
            "ta": "ஒப்புதலுக்காக காத்திருக்கிறது",
            "en": "Awaiting sign-off",
        },
        "APPROVED": {"si": "අනුමතයි", "ta": "அங்கீகரிக்கப்பட்டது", "en": "Approved"},
        "REJECTED": {"si": "ප්‍රතික්ෂේපිත", "ta": "நிராகரிக்கப்பட்டது", "en": "Rejected"},
        "RELEASED": {"si": "නිකුත් කර ඇත", "ta": "விடுவிக்கப்பட்டது", "en": "Released"},
        "COMPLETED": {"si": "සම්පූර්ණයි", "ta": "நிறைவடைந்தது", "en": "Completed"},
    },
}


# The catalogue served by /api/v1/meta/reference: taxonomy name to its ordered values.
CATALOGUE: Final[dict[str, tuple[str, ...]]] = {
    "locales": LOCALES,
    "hazard_types": HAZARD_TYPES,
    "hazard_statuses": HAZARD_STATUSES,
    "incident_statuses": INCIDENT_STATUSES,
    "intake_channels": INTAKE_CHANNELS,
    "damage_categories": DAMAGE_CATEGORIES,
    "entitlement_statuses": ENTITLEMENT_STATUSES,
    "payment_rails": PAYMENT_RAILS,
    "alert_statuses": ALERT_STATUSES,
    "dispatch_statuses": DISPATCH_STATUSES,
}


def labels_for(taxonomy: str, value: str) -> dict[str, str]:
    """The trilingual labels for one value.

    Raises:
        KeyError: if the taxonomy or value has no labels. Every value must have all three;
            a missing one is a build error, not a runtime fallback to English.
    """
    return _LABELS[taxonomy][value]


def reference_catalogue() -> dict[str, list[dict[str, object]]]:
    """The whole catalogue, shaped for the meta endpoint.

    Each entry is `{value, labels: {si, ta, en}}` rather than a bare string, so a client
    never has to hold its own translation table for a status code.
    """
    return {
        name: [{"value": value, "labels": labels_for(name, value)} for value in values]
        for name, values in CATALOGUE.items()
    }


def missing_labels() -> list[tuple[str, str]]:
    """Every (taxonomy, value) with absent or incomplete labels.

    Exposed so a test can assert the list is empty. A taxonomy the platform serves in
    fewer than three languages is one that reaches a citizen in a language they may not
    read, which is the failure this whole convention exists to prevent.
    """
    gaps: list[tuple[str, str]] = []
    for name, values in CATALOGUE.items():
        for value in values:
            labels = _LABELS.get(name, {}).get(value)
            if not labels or any(not labels.get(locale, "").strip() for locale in LOCALES):
                gaps.append((name, value))
    return gaps
