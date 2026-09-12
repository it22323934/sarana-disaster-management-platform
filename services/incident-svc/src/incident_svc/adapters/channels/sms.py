"""Inbound SMS.

Two things must both work: the documented `HELP <type> <text>` syntax, and whatever a
frightened person actually types. The second is the real case.

Nobody remembers a syntax during an emergency. A parser that only accepted the documented
form would drop the messages that matter most, so an unparseable message is never
rejected - it becomes a report with the text intact and no type, and a human sees it.
"""

from __future__ import annotations

import re
from typing import Final

from incident_svc.adapters.channels.intake import ReportIntake
from incident_svc.domain.triage import INCIDENT_TYPE_WEIGHTS

CHANNEL: Final = "SMS"

# `HELP FLOOD water rising fast`, case-insensitive, any amount of whitespace.
_STRUCTURED: Final = re.compile(
    r"^\s*(?:HELP|උදව්|உதவி)\s+(?P<type>[A-Za-z_]+)\s*(?P<text>.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Words that signal an incident type in free text. Sinhala and Tamil included because a
# keyword match that only worked in English would work for the smallest group of users.
#
# **Order is significant: most urgent first.** A message matches on the first entry that
# hits, and real messages describe several things at once. "trapped on the roof, water
# rising" is a person trapped, not a flood report - the flood is why they are trapped, and
# routing it as a flood puts a rescue behind a sandbag delivery.
_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "TRAPPED": ("trapped", "stuck", "drowning", "සිරවී", "අතරමං", "சிக்கி"),
    "MEDICAL": ("injured", "bleeding", "sick", "තුවාල", "රෝගී", "காயம்", "நோய்"),
    "STRUCTURAL_COLLAPSE": ("collapse", "fell", "කඩා", "இடிந்து"),
    "LANDSLIDE": ("landslide", "slip", "නායයෑම", "නාය", "நிலச்சரிவு"),
    "FLOOD": ("flood", "water", "ගංවතුර", "වතුර", "வெள்ளம்", "தண்ணீர்"),
    "MISSING_PERSON": ("missing", "lost", "නැති", "காணவில்லை"),
    "EVACUATION_NEEDED": ("evacuate", "rescue", "ඉවත්", "மீட்பு"),
    "SUPPLIES_NEEDED": ("food", "hungry", "shelter", "ආහාර", "නවාතැන", "உணவு", "தங்குமிடம்"),
}

# Very rough script detection, enough to record which language the message arrived in so a
# reply goes back in the same one. Not a substitute for the transcription pipeline.
_SINHALA_RANGE: Final = (0x0D80, 0x0DFF)
_TAMIL_RANGE: Final = (0x0B80, 0x0BFF)


def detect_language(text: str) -> str | None:
    """si, ta, en, or None when there is nothing to go on."""
    if not text.strip():
        return None
    for character in text:
        code = ord(character)
        if _SINHALA_RANGE[0] <= code <= _SINHALA_RANGE[1]:
            return "si"
        if _TAMIL_RANGE[0] <= code <= _TAMIL_RANGE[1]:
            return "ta"
    return "en" if any(character.isascii() and character.isalpha() for character in text) else None


def detect_type(text: str) -> str | None:
    """Guess an incident type from keywords, or None.

    None is a perfectly good answer. An unrecognised message keeps its text and reaches a
    human; guessing wrong would route it to the wrong queue with false confidence.
    """
    lowered = text.lower()
    for incident_type, words in _KEYWORDS.items():
        if any(word in lowered for word in words):
            return incident_type
    return None


def parse(
    *, body: str, sender_msisdn_hash: str, correlation_id: str, **metadata: object
) -> ReportIntake:
    """Turn one inbound SMS into a report.

    Never raises on content. The only thing that can fail here is the channel being
    unknown, which is a programming error rather than a citizen's message.
    """
    text = body.strip()
    incident_type: str | None = None

    match = _STRUCTURED.match(text)
    if match:
        candidate = match.group("type").upper()
        remainder = match.group("text").strip()
        if candidate in INCIDENT_TYPE_WEIGHTS:
            incident_type = candidate
            text = remainder or text
        else:
            # `HELP` followed by something that is not a type is just free text. The word
            # was the citizen asking for help, which is not a parse failure.
            text = f"{match.group('type')} {remainder}".strip()

    if incident_type is None:
        incident_type = detect_type(text)

    return ReportIntake(
        channel=CHANNEL,
        correlation_id=correlation_id,
        raw_text=text or None,
        reported_language=detect_language(text),
        incident_type=incident_type,
        sender_msisdn_hash=sender_msisdn_hash,
        channel_metadata={"structured": bool(match), **metadata},
    )
