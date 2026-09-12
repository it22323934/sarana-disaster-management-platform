"""Language detection by script, and the trilingual hazard lexicon behind the degraded path.

## Language detection is a script test, not a model call

Sinhala occupies U+0D80-U+0DFF and Tamil U+0B80-U+0BFF, and neither shares a codepoint with
the other or with Latin. So detecting which language a report is written in is a character
range check: exact, instant, free, and impossible to get wrong in the way a classifier gets
things wrong. Spending a model call on this would be slower, cost money, and be less
reliable.

What the script test cannot do is tell Sinhala prose from a Sinhala word dropped into an
English sentence, so `detect` reports the **mix** rather than a single winner, and
`code_switched` is a first-class answer. Code-switching is normal in Sri Lanka and it is
the hardest input this platform receives - it is also disproportionately likely to come
from somebody who is not writing carefully, which during a cyclone is everybody.

## The lexicon is the degraded extraction path

With no model provider, extraction is keyword matching over this table. That is materially
worse than a model and it is not nothing: "ගංවතුර" in a report is a flood report whoever
reads it, and a queue of correctly-typed reports that a human confirms is a working
platform. Every output from this path is labelled `DETERMINISTIC` and every one of them is
routed for human confirmation.

The words are the ones people actually send, not the dictionary forms. They came from the
seeded alert templates (file 09), which are native-speaker reviewed, plus the hazard
vocabulary the Met Department and NBRO publish in their own bulletins. **A native speaker
should review any addition to this table**, for the same reason one reviews an alert
template: a wrong keyword here mistypes an emergency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# The Unicode blocks. Nothing else in the Basic Multilingual Plane collides with either.
SINHALA_RANGE: Final = (0x0D80, 0x0DFF)
TAMIL_RANGE: Final = (0x0B80, 0x0BFF)

# Below this share of the letters, a script is treated as incidental rather than the
# language of the report. A single Sinhala place name in an English SMS does not make it a
# Sinhala report, and routing it to a Sinhala reviewer would waste their time.
INCIDENTAL_SHARE: Final = 0.15

# At or above this share, a second script means the report genuinely mixes languages.
# Deliberately low: a report that is four-fifths Sinhala with an English street name in it
# is one where the English matters, because the street name is where somebody is going.
CODE_SWITCH_SHARE: Final = 0.15


@dataclass(frozen=True, slots=True)
class LanguageMix:
    """What scripts a report is written in, and in what proportion.

    A mix rather than a winner. `primary` is what a reviewer should read it in;
    `code_switched` is what the model router upgrades a tier on.
    """

    primary: str
    shares: dict[str, float]
    letters: int

    @property
    def code_switched(self) -> bool:
        """Whether more than one language is genuinely present."""
        return sum(1 for share in self.shares.values() if share >= CODE_SWITCH_SHARE) > 1

    @property
    def languages(self) -> tuple[str, ...]:
        """Every language present above the incidental threshold, most present first."""
        present = [
            (code, share) for code, share in self.shares.items() if share >= INCIDENTAL_SHARE
        ]
        return tuple(code for code, _ in sorted(present, key=lambda pair: -pair[1]))

    @property
    def confidence(self) -> float:
        """How sure the script test is.

        Not a model's confidence and not calibrated against anything - it is the share of
        letters belonging to the winning script, which is a fact rather than a belief. It
        is reported so a downstream gate can see that a two-word report said less than a
        two-sentence one.
        """
        if self.letters == 0:
            return 0.0
        return round(self.shares.get(self.primary, 0.0), 3)


def script_of(character: str) -> str | None:
    """Which language's script a character belongs to, or None if it is not a letter.

    Digits, punctuation and whitespace return None rather than counting as English. A
    report reading "0771234567" is not an English report; it is a phone number, and letting
    it vote would make every numeric SMS look confidently English.
    """
    point = ord(character)
    if SINHALA_RANGE[0] <= point <= SINHALA_RANGE[1]:
        return "si"
    if TAMIL_RANGE[0] <= point <= TAMIL_RANGE[1]:
        return "ta"
    if character.isascii() and character.isalpha():
        return "en"
    return None


def detect(text: str) -> LanguageMix:
    """Which languages this report is written in.

    Empty or scriptless text reports English at zero confidence rather than raising. A
    report with no letters in it - a bare GPS ping, a photo with no caption - is a real
    thing that arrives, and it is still dispatchable on its coordinate.
    """
    counts: dict[str, int] = {"si": 0, "ta": 0, "en": 0}
    for character in text:
        script = script_of(character)
        if script is not None:
            counts[script] += 1

    letters = sum(counts.values())
    if letters == 0:
        return LanguageMix(primary="en", shares={}, letters=0)

    shares = {code: count / letters for code, count in counts.items() if count}
    primary = max(shares, key=lambda code: shares[code])
    return LanguageMix(primary=primary, shares=shares, letters=letters)


# The hazard vocabulary, per incident type, in all three languages.
#
# Matched case-insensitively as substrings, because Sinhala and Tamil are agglutinative and
# the inflected form a person types is rarely the citation form. Substring matching over a
# short list is crude and it fails in the safe direction: it over-matches, and every match
# from this path goes to a human anyway.
#
# The keys are exactly `incident.incident`'s CHECK vocabulary. A type this produces that the
# column rejects would fail at the INSERT, after the report was accepted; a test asserts the
# two lists agree.
HAZARD_LEXICON: Final[dict[str, tuple[str, ...]]] = {
    # No bare word for "water" in any language, here or in the supplies list below.
    # `ජලය`, `நீர்` and "water" all mean water and say nothing about whether it is rising
    # through somebody's door or missing from their tap. Worse, `நீர்` is a substring of
    # `தண்ணீர்` (drinking water), so a Tamil flood report matched the supplies list and was
    # typed as a request for a bottle. Substring matching over a short list only works when
    # the terms are specific; the generic ones are exactly what breaks it.
    "FLOOD": (
        "ගංවතුර",
        "වතුර ගලා",
        "වතුර පිරී",
        "வெள்ளம்",
        "வெள்ள",
        "flood",
        "water rising",
        "water is rising",
        "inundat",
        "submerged",
    ),
    "LANDSLIDE": (
        "නායයෑම",
        "නාය",
        "බෑවුම",
        "நிலச்சரிவு",
        "மண்சரிவு",
        "landslide",
        "mudslide",
        "slope",
        "earth slip",
    ),
    "STRUCTURAL_COLLAPSE": (
        "කඩාවැටුණ",
        "කඩා වැටී",
        "ගොඩනැගිල්ල",
        "இடிந்து",
        "கட்டிடம்",
        "collapse",
        "house fell",
        "building down",
        "roof came down",
    ),
    "MEDICAL": (
        "රෝගී",
        "තුවාල",
        "අසනීප",
        "காயம்",
        "நோய்",
        "மருத்துவ",
        "injured",
        "bleeding",
        "unconscious",
        "medical",
        "hospital",
        "ambulance",
    ),
    "MISSING_PERSON": (
        "අතුරුදහන්",
        "නැති වී",
        "காணவில்லை",
        "தொலைந்த",
        "missing",
        "cannot find",
        "lost child",
    ),
    "TRAPPED": (
        "සිරවී",
        "හිර වී",
        "අගුලු",
        "சிக்கி",
        "மாட்டிக்",
        "trapped",
        "stuck",
        "cannot get out",
        "on the roof",
    ),
    "EVACUATION_NEEDED": (
        "ඉවත් ",
        "ගලවා",
        "வெளியேற",
        "மீட்க",
        "evacuat",
        "rescue",
        "to leave",
        "get us out",
        "help us move",
    ),
    "SUPPLIES_NEEDED": (
        "ආහාර",
        "කෑම",
        "බොන වතුර",
        "உணவு",
        "குடிநீர்",
        "food",
        "drinking water",
        "supplies",
        "milk powder",
        "medicine",
    ),
    "INFRASTRUCTURE": (
        "පාලම",
        "මාර්ගය",
        "විදුලිය",
        "பாலம்",
        "சாலை",
        "மின்சாரம்",
        "bridge",
        "road closed",
        "power",
        "electricity",
        "no signal",
    ),
}

# Words that say somebody is in danger right now, whatever the incident type is. Kept apart
# from the type lexicon because urgency and type are different questions: a supplies request
# and a trapped family are both real, and only one of them cannot wait.
IMMEDIATE_DANGER_TERMS: Final[tuple[str, ...]] = (
    "දැන්",
    "වහාම",
    "උදව්",
    "බේරගන්න",
    "இப்போது",
    "உடனே",
    "உதவி",
    "காப்பாற்று",
    "now",
    "urgent",
    "immediately",
    "help us",
    "dying",
    "drowning",
    "cannot breathe",
)

# People whose presence changes who is sent and how fast. The categories match
# `ExtractedReport.vulnerable_present`, which the triage weighting reads.
VULNERABILITY_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "elderly": (
        "වයස්ගත",
        "මහලු",
        "ආච්චි",
        "සීයා",
        "முதியவர்",
        "வயதான",
        "elderly",
        "old man",
        "old woman",
        "grandmother",
        "grandfather",
    ),
    "children": (
        "ළමයි",
        "දරුවන්",
        "බබා",
        "குழந்தை",
        "பிள்ளை",
        "child",
        "children",
        "baby",
        "infant",
        "kids",
    ),
    "injured": ("තුවාල", "රුධිර", "காயம்", "ரத்த", "injured", "bleeding", "wound", "broken leg"),
    "pregnant": ("ගැබිනි", "දරුප්‍රසූත", "கர்ப்ப", "pregnant", "in labour", "expecting"),
    "disabled": (
        "ආබාධිත",
        "ඇවිදින්න බැරි",
        "ஊனமுற்ற",
        "disabled",
        "wheelchair",
        "cannot walk",
        "bedridden",
    ),
}


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    """Every term present in the text, in the order the table lists them."""
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def incident_types_in(text: str) -> list[tuple[str, list[str]]]:
    """Every incident type the lexicon finds, most evidence first.

    All of them rather than the best one. A report saying a house collapsed and somebody is
    trapped is both, and picking one would throw away the half that decides how fast a crew
    moves. The caller chooses; this only reports what is there.
    """
    found = [
        (incident_type, hits)
        for incident_type, terms in HAZARD_LEXICON.items()
        if (hits := _matches(text, terms))
    ]
    return sorted(found, key=lambda pair: -len(pair[1]))


def immediate_danger_in(text: str) -> list[str]:
    """Words saying somebody is in danger right now."""
    return _matches(text, IMMEDIATE_DANGER_TERMS)


def vulnerabilities_in(text: str) -> dict[str, list[str]]:
    """Which vulnerable groups the text names, and the words that said so."""
    return {
        group: hits
        for group, terms in VULNERABILITY_TERMS.items()
        if (hits := _matches(text, terms))
    }


def keyword_context(division_names: list[str], *, limit: int = 60) -> str:
    """The ASR prompt hint: place names plus the standing hazard vocabulary.

    Build file 15 calls this the single highest-leverage accuracy improvement available,
    and it costs nothing - a transcriber that has been told "Gampola" and "නායයෑම" are
    likely words is dramatically better at hearing them in a bad phone recording.

    Bounded, because the hint is a prompt and an unbounded one is an unbounded cost on
    every report. Place names come first: the hazard vocabulary is the same on every report
    and the division names are what this one is about.
    """
    hazard_words = [terms[0] for terms in HAZARD_LEXICON.values()]
    words = [*division_names, *hazard_words]
    return ", ".join(words[:limit])
