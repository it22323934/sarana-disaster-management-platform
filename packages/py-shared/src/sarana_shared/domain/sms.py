"""How many SMS segments a message costs, and why that is a life-safety concern.

A GSM message is not billed or transmitted by characters, it is transmitted by segments.
Which alphabet the text falls into decides how many characters fit in one:

  **GSM-7** — the Latin alphabet plus a small extension table. 160 characters in a single
  segment, 153 in each part of a concatenated one, because the concatenation header eats
  seven characters' worth of every part.

  **UCS-2** — everything else, which for SARANA means *every Sinhala and Tamil message we
  will ever send*. 70 characters single, 67 concatenated.

That asymmetry is the whole point of this module. An English warning that fits comfortably
in one segment becomes three segments in Sinhala, and during a national fan-out three
segments is three times the cost, three times the gateway queue, and three separate parts
that can arrive out of order or not at all on a congested network. The community reading
the Tamil version is the one whose warning arrives last and truncated — which is the exact
Ditwah failure this platform exists to correct, reproduced by a billing detail.

So the limit is enforced in CI (`python -m tools.sms_segment_check`) rather than measured
after an event. A template whose Sinhala or Tamil rendering exceeds two segments does not
ship.

**Segments are counted in UTF-16 code units, not Python characters.** They are the same
number for Sinhala and Tamil, which live entirely in the Basic Multilingual Plane, and they
differ for an emoji — which is exactly the case where counting characters would under-count
and let a message through that the gateway then splits into one more part than we budgeted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# GSM 03.38 basic character set. A character outside this and the extension below forces
# the whole message to UCS-2 — one Sinhala letter in an otherwise English message costs
# the same as a wholly Sinhala one, which is why mixed-script templates are a trap.
GSM7_BASIC: Final[frozenset[str]] = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)

# The extension table. Each of these is transmitted as an escape plus the character, so it
# costs two of the seven-bit units rather than one.
GSM7_EXTENDED: Final[frozenset[str]] = frozenset("^{}\[~]|€")

# Characters per segment, per alphabet. The concatenated figures are lower because a
# multipart message carries a User Data Header in every part.
GSM7_SINGLE: Final = 160
GSM7_CONCATENATED: Final = 153
UCS2_SINGLE: Final = 70
UCS2_CONCATENATED: Final = 67

# The ceiling a citizen-facing template must fit inside, in every language.
#
# Two rather than one, because a useful evacuation instruction naming a division and a
# shelter does not fit in 70 UCS-2 characters and writing to that limit would strip the
# place names that make the message actionable. Two rather than three, because each extra
# part is another chance for the message to arrive incomplete on a network that is already
# the reason people are being warned by SMS.
MAX_SEGMENTS: Final = 2


class SmsEncoding(StrEnum):
    """Which alphabet a message falls into."""

    GSM7 = "GSM7"
    UCS2 = "UCS2"


def encoding_for(text: str) -> SmsEncoding:
    """Which alphabet this text needs.

    One character outside GSM-7 moves the entire message to UCS-2. There is no partial
    encoding: the alphabet is a property of the message, not of its characters.
    """
    for character in text:
        if character not in GSM7_BASIC and character not in GSM7_EXTENDED:
            return SmsEncoding.UCS2
    return SmsEncoding.GSM7


def units_in(text: str) -> int:
    """The transmitted length of the text, in the units its alphabet is measured in.

    For GSM-7 that is septets, with the extension-table characters counting twice. For
    UCS-2 it is UTF-16 code units, so a character outside the Basic Multilingual Plane
    counts as the two units it actually occupies — the case where counting Python
    characters would under-count and let a message through that the gateway then splits
    into one more part than was budgeted for.
    """
    if encoding_for(text) is SmsEncoding.GSM7:
        return sum(2 if character in GSM7_EXTENDED else 1 for character in text)
    return len(text.encode("utf-16-le")) // 2


@dataclass(frozen=True, slots=True)
class SegmentCount:
    """What one rendered message costs on the wire."""

    text_length: int
    encoding: SmsEncoding
    units: int
    segments: int
    limit_at_max: int

    @property
    def within_limit(self) -> bool:
        return self.segments <= MAX_SEGMENTS

    @property
    def headroom(self) -> int:
        """Units still available before the message needs another segment.

        Negative when it is already over. Reported rather than a bare pass/fail because a
        template sitting one character under the limit is one an operator will break with
        the next place name, and the author should see that while they are still writing.
        """
        return self.limit_at_max - self.units

    def as_sentence(self) -> str:
        return (
            f"{self.units} {self.encoding.value} units in {self.segments} segment"
            f"{'' if self.segments == 1 else 's'} "
            f"({self.headroom:+d} against the {self.limit_at_max}-unit limit)"
        )


def count(text: str, *, max_segments: int = MAX_SEGMENTS) -> SegmentCount:
    """How many segments this message takes, and how much room is left.

    An empty message is one segment, not zero: a gateway asked to send nothing still sends
    something, and reporting zero would let an empty template pass a length check that
    exists to catch exactly the templates nobody looked at.
    """
    encoding = encoding_for(text)
    units = units_in(text)

    if encoding is SmsEncoding.GSM7:
        single, concatenated = GSM7_SINGLE, GSM7_CONCATENATED
    else:
        single, concatenated = UCS2_SINGLE, UCS2_CONCATENATED

    if units <= single:
        segments = 1
    else:
        segments = -(-units // concatenated)  # ceiling division

    return SegmentCount(
        text_length=len(text),
        encoding=encoding,
        units=units,
        segments=segments,
        limit_at_max=single if max_segments == 1 else concatenated * max_segments,
    )


def fits(text: str, *, max_segments: int = MAX_SEGMENTS) -> bool:
    """Whether this message ships. The one-line form, for a call site that only branches."""
    return count(text, max_segments=max_segments).segments <= max_segments
