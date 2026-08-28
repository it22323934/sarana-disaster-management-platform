"""The twelve Phase 1 alert templates.

Build file 09 names exactly these twelve: flood watch, flood warning, evacuate now,
landslide watch, landslide warning, cyclone warning, storm surge, shelter open, shelter
full, road closed, all-clear, aid distribution point open.

**Every one is seeded as DRAFT with no reviewer signatures.** That is deliberate and it is
the whole point of the gate: a template becomes dispatchable only when a named Sinhala
reviewer and a named Tamil reviewer have each signed it. Seeding them as PUBLISHED would
put twelve machine-translated life-safety messages one API call away from a district,
which is exactly what the review workflow exists to prevent.

The Sinhala and Tamil bodies here are working translations and are **not** a substitute
for that review. A native speaker signs, or nothing ships.
"""

from __future__ import annotations

from typing import Any, Final

# code, hazard, severity, urgency, certainty, {si, ta, en}
TEMPLATES: Final[tuple[dict[str, Any], ...]] = (
    {
        "code": "FLOOD_WATCH",
        "hazard_type": "FLOOD",
        "severity": "MODERATE",
        "urgency": "FUTURE",
        "certainty": "POSSIBLE",
        "body": {
            "si": "{gn_division_name} ප්‍රදේශයේ ගංවතුර අවදානමක් ඇත. ජල මට්ටම නිරීක්ෂණය කරන්න.",
            "ta": "{gn_division_name} பகுதியில் வெள்ள அபாயம் உள்ளது. நீர்மட்டத்தை கவனியுங்கள்.",
            "en": "Flood risk in {gn_division_name}. Monitor water levels.",
        },
    },
    {
        "code": "FLOOD_WARNING",
        "hazard_type": "FLOOD",
        "severity": "SEVERE",
        "urgency": "EXPECTED",
        "certainty": "LIKELY",
        "body": {
            "si": "{gn_division_name} ප්‍රදේශයේ ගංවතුර අනතුරු ඇඟවීම. උස් බිමකට යාමට සූදානම් වන්න.",
            "ta": ("{gn_division_name} பகுதியில் வெள்ள எச்சரிக்கை. உயரமான இடத்திற்கு செல்ல தயாராகுங்கள்."),
            "en": "Flood warning for {gn_division_name}. Prepare to move to higher ground.",
        },
    },
    {
        "code": "FLOOD_EVACUATE_IMMEDIATE",
        "hazard_type": "FLOOD",
        "severity": "EXTREME",
        "urgency": "IMMEDIATE",
        "certainty": "OBSERVED",
        "body": {
            "si": (
                "{gn_division_name} ප්‍රදේශයෙන් දැන්ම ඉවත් වන්න. {shelter_name} වෙත "
                "{deadline_time} ට පෙර යන්න."
            ),
            "ta": (
                "{gn_division_name} பகுதியிலிருந்து இப்போதே வெளியேறுங்கள். {deadline_time} "
                "க்கு முன் {shelter_name} செல்லுங்கள்."
            ),
            "en": "Evacuate {gn_division_name} now. Go to {shelter_name} before {deadline_time}.",
        },
    },
    {
        "code": "LANDSLIDE_WATCH",
        "hazard_type": "LANDSLIDE",
        "severity": "MODERATE",
        "urgency": "FUTURE",
        "certainty": "POSSIBLE",
        "body": {
            "si": "{gn_division_name} ප්‍රදේශයේ නායයෑම් අවදානමක් ඇත. බෑවුම් වලින් ඈත් වන්න.",
            "ta": ("{gn_division_name} பகுதியில் நிலச்சரிவு அபாயம். சரிவுகளிலிருந்து விலகி இருங்கள்."),
            "en": "Landslide risk in {gn_division_name}. Stay away from slopes.",
        },
    },
    {
        "code": "LANDSLIDE_WARNING",
        "hazard_type": "LANDSLIDE",
        "severity": "SEVERE",
        "urgency": "IMMEDIATE",
        "certainty": "LIKELY",
        "body": {
            "si": "{gn_division_name} ප්‍රදේශයේ නායයෑම් අනතුරු ඇඟවීම. {shelter_name} වෙත යන්න.",
            "ta": "{gn_division_name} பகுதியில் நிலச்சரிவு எச்சரிக்கை. {shelter_name} செல்லுங்கள்.",
            "en": "Landslide warning for {gn_division_name}. Move to {shelter_name}.",
        },
    },
    {
        "code": "CYCLONE_WARNING",
        "hazard_type": "CYCLONE",
        "severity": "EXTREME",
        "urgency": "IMMEDIATE",
        "certainty": "LIKELY",
        "body": {
            "si": ("{gn_division_name} වෙත සුළිකුණාටුවක් ළඟා වේ. {deadline_time} ට පෙර ආරක්ෂිත ස්ථානයකට යන්න."),
            "ta": (
                "{gn_division_name} நோக்கி சூறாவளி நெருங்குகிறது. {deadline_time} க்கு முன் "
                "பாதுகாப்பான இடத்திற்கு செல்லுங்கள்."
            ),
            "en": "Cyclone approaching {gn_division_name}. Reach shelter before {deadline_time}.",
        },
    },
    {
        "code": "STORM_SURGE_WARNING",
        "hazard_type": "STORM_SURGE",
        "severity": "EXTREME",
        "urgency": "IMMEDIATE",
        "certainty": "LIKELY",
        "body": {
            "si": ("{gn_division_name} වෙරළ ප්‍රදේශයට කුණාටු රළ. වෙරළෙන් ඈත් වී {shelter_name} වෙත යන්න."),
            "ta": (
                "{gn_division_name} கடற்கரையில் புயல் அலை. கடற்கரையிலிருந்து விலகி "
                "{shelter_name} செல்லுங்கள்."
            ),
            "en": "Storm surge on the {gn_division_name} coast. Move inland to {shelter_name}.",
        },
    },
    {
        "code": "SHELTER_OPEN",
        "hazard_type": "FLOOD",
        "severity": "MINOR",
        "urgency": "EXPECTED",
        "certainty": "OBSERVED",
        "body": {
            "si": "{shelter_name} නවාතැන {gn_division_name} ප්‍රදේශය සඳහා විවෘතයි.",
            "ta": "{gn_division_name} பகுதிக்காக {shelter_name} தங்குமிடம் திறந்துள்ளது.",
            "en": "{shelter_name} shelter is open for {gn_division_name}.",
        },
    },
    {
        "code": "SHELTER_FULL",
        "hazard_type": "FLOOD",
        "severity": "MINOR",
        "urgency": "EXPECTED",
        "certainty": "OBSERVED",
        "body": {
            "si": "{shelter_name} නවාතැන පිරී ඇත. {gn_division_name} ජනතාව වෙනත් ස්ථානයකට යන්න.",
            "ta": (
                "{shelter_name} தங்குமிடம் நிரம்பிவிட்டது. {gn_division_name} "
                "மக்கள் வேறு இடத்திற்கு செல்லவும்."
            ),
            "en": "{shelter_name} is full. Residents of {gn_division_name} should go elsewhere.",
        },
    },
    {
        "code": "ROAD_CLOSED",
        "hazard_type": "FLOOD",
        "severity": "MODERATE",
        "urgency": "EXPECTED",
        "certainty": "OBSERVED",
        "body": {
            "si": "{road_name} මාර්ගය {gn_division_name} ප්‍රදේශයේ වසා ඇත.",
            "ta": "{gn_division_name} பகுதியில் {road_name} சாலை மூடப்பட்டுள்ளது.",
            "en": "{road_name} is closed in {gn_division_name}.",
        },
    },
    {
        "code": "ALL_CLEAR",
        "hazard_type": "FLOOD",
        "severity": "MINOR",
        "urgency": "PAST",
        "certainty": "OBSERVED",
        "body": {
            "si": "{gn_division_name} ප්‍රදේශයේ අනතුර පහව ගොස් ඇත. ආපසු යාම ආරක්ෂිතයි.",
            "ta": "{gn_division_name} பகுதியில் ஆபத்து நீங்கியுள்ளது. திரும்புவது பாதுகாப்பானது.",
            "en": "All clear for {gn_division_name}. It is safe to return.",
        },
    },
    {
        "code": "AID_DISTRIBUTION_OPEN",
        "hazard_type": "FLOOD",
        "severity": "MINOR",
        "urgency": "EXPECTED",
        "certainty": "OBSERVED",
        "body": {
            "si": "{gn_division_name} සඳහා {distribution_point} හි ආධාර බෙදාහැරීම විවෘතයි.",
            "ta": "{gn_division_name} க்கான உதவி விநியோகம் {distribution_point} இல் திறந்துள்ளது.",
            "en": "Aid distribution open at {distribution_point} for {gn_division_name}.",
        },
    },
)
