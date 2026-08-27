"""The USSD menu, as a state machine.

Constraints from the build brief, all of which are about the phone rather than the code:
at most four levels deep, every screen under 160 characters in all three languages, and
the language chosen on the first screen.

USSD is what works on a feature phone with no data and one bar of signal, which describes
a great many people during a flood. It is the channel most likely to be used by someone
with no alternative, so it gets the shortest path to a submitted report: language, type,
people, confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from incident_svc.adapters.channels.intake import ReportIntake

CHANNEL: Final = "USSD"

# A USSD screen is 182 bytes on most networks; 160 is the safe limit and the one the brief
# sets. Enforced by a test over every screen in every language, because a screen that
# overflows is silently truncated by the network and the last option disappears.
MAX_SCREEN_CHARS: Final = 160


class Step(StrEnum):
    """Four levels, as required. `DONE` is a result, not a screen."""

    LANGUAGE = "language"
    TYPE = "type"
    PEOPLE = "people"
    CONFIRM = "confirm"
    DONE = "done"


# The incident types offered. A short list on purpose: a menu of fourteen options on a
# feature phone is a menu nobody reaches the end of. Anything not here arrives by SMS or
# voice as free text.
MENU_TYPES: Final[tuple[str, ...]] = (
    "FLOOD",
    "LANDSLIDE",
    "TRAPPED",
    "MEDICAL",
    "EVACUATION_NEEDED",
)

SCREENS: Final[dict[Step, dict[str, str]]] = {
    Step.LANGUAGE: {
        "si": "SARANA\n1. සිංහල\n2. தமிழ்\n3. English",
        "ta": "SARANA\n1. සිංහල\n2. தமிழ்\n3. English",
        "en": "SARANA\n1. සිංහල\n2. தமிழ்\n3. English",
    },
    Step.TYPE: {
        "si": "කුමක් සිදුවිද?\n1. ගංවතුර\n2. නායයෑම\n3. සිරවී\n4. වෛද්‍ය\n5. ඉවත් කිරීම",
        "ta": "என்ன நடந்தது?\n1. வெள்ளம்\n2. நிலச்சரிவு\n3. சிக்கி\n4. மருத்துவம்\n5. வெளியேற்றம்",
        "en": "What happened?\n1. Flood\n2. Landslide\n3. Trapped\n4. Medical\n5. Evacuate",
    },
    Step.PEOPLE: {
        "si": "කී දෙනෙක් අවදානමේ?\n1. 1-2\n2. 3-5\n3. 6-10\n4. 10+",
        "ta": "எத்தனை பேர் ஆபத்தில்?\n1. 1-2\n2. 3-5\n3. 6-10\n4. 10+",
        "en": "How many at risk?\n1. 1-2\n2. 3-5\n3. 6-10\n4. 10+",
    },
    Step.CONFIRM: {
        "si": "යවන්නද?\n1. ඔව්\n2. නැත",
        "ta": "அனுப்பவா?\n1. ஆம்\n2. இல்லை",
        "en": "Send report?\n1. Yes\n2. No",
    },
}

SENT: Final[dict[str, str]] = {
    "si": "වාර්තා විය. උදව් එනවා.",
    "ta": "அறிக்கை பெறப்பட்டது. உதவி வருகிறது.",
    "en": "Report received. Help is on the way.",
}

CANCELLED: Final[dict[str, str]] = {
    "si": "අවලංගු කළා.",
    "ta": "ரத்து செய்யப்பட்டது.",
    "en": "Cancelled.",
}

_LANGUAGES: Final[dict[str, str]] = {"1": "si", "2": "ta", "3": "en"}

# Midpoints, not ranges. A dispatcher needs one number to rank on, and the bucket is
# recorded in the metadata so the estimate is never mistaken for a headcount.
_PEOPLE: Final[dict[str, int]] = {"1": 2, "2": 4, "3": 8, "4": 12}


class SessionExpired(Exception):
    """The session has no state. The network dropped it, or it is being replayed."""


@dataclass(frozen=True, slots=True)
class SessionState:
    """Where one caller is in the menu."""

    step: Step = Step.LANGUAGE
    language: str = "en"
    incident_type: str | None = None
    people_at_risk: int | None = None
    people_bucket: str | None = None


@dataclass(frozen=True, slots=True)
class Turn:
    """What to show the caller, and whether the session is finished."""

    text: str
    state: SessionState
    finished: bool = False
    intake: ReportIntake | None = None


def screen(step: Step, language: str) -> str:
    """The text for one screen in one language."""
    return SCREENS[step][language]


def start() -> Turn:
    """The first screen. Language before anything else, so nothing is ever asked in a
    language the caller may not read."""
    state = SessionState()
    return Turn(text=screen(Step.LANGUAGE, "en"), state=state)


def advance(
    state: SessionState,
    choice: str,
    *,
    sender_msisdn_hash: str,
    correlation_id: str,
) -> Turn:
    """Apply one keypress.

    An invalid choice re-shows the same screen rather than ending the session. Ending it
    would mean starting over on a phone that may not reconnect.
    """
    choice = choice.strip()

    if state.step is Step.LANGUAGE:
        language = _LANGUAGES.get(choice)
        if language is None:
            return Turn(text=screen(Step.LANGUAGE, state.language), state=state)
        moved = SessionState(step=Step.TYPE, language=language)
        return Turn(text=screen(Step.TYPE, language), state=moved)

    if state.step is Step.TYPE:
        index = _menu_index(choice, len(MENU_TYPES))
        if index is None:
            return Turn(text=screen(Step.TYPE, state.language), state=state)
        moved = SessionState(
            step=Step.PEOPLE,
            language=state.language,
            incident_type=MENU_TYPES[index],
        )
        return Turn(text=screen(Step.PEOPLE, state.language), state=moved)

    if state.step is Step.PEOPLE:
        people = _PEOPLE.get(choice)
        if people is None:
            return Turn(text=screen(Step.PEOPLE, state.language), state=state)
        moved = SessionState(
            step=Step.CONFIRM,
            language=state.language,
            incident_type=state.incident_type,
            people_at_risk=people,
            people_bucket=choice,
        )
        return Turn(text=screen(Step.CONFIRM, state.language), state=moved)

    if state.step is Step.CONFIRM:
        if choice == "1":
            intake = ReportIntake(
                channel=CHANNEL,
                correlation_id=correlation_id,
                reported_language=state.language,
                incident_type=state.incident_type,
                people_at_risk=state.people_at_risk,
                sender_msisdn_hash=sender_msisdn_hash,
                # No location: USSD carries none. The sender's household, resolved by
                # HMAC, is the only positional information this channel has.
                location_source="inferred",
                channel_metadata={"people_bucket": state.people_bucket, "menu": "v1"},
            )
            done = SessionState(step=Step.DONE, language=state.language)
            return Turn(text=SENT[state.language], state=done, finished=True, intake=intake)
        if choice == "2":
            done = SessionState(step=Step.DONE, language=state.language)
            return Turn(text=CANCELLED[state.language], state=done, finished=True)
        return Turn(text=screen(Step.CONFIRM, state.language), state=state)

    raise SessionExpired("this USSD session has already finished")


def _menu_index(choice: str, options: int) -> int | None:
    """Convert a keypress to a zero-based index, or None."""
    if not choice.isdigit():
        return None
    index = int(choice) - 1
    return index if 0 <= index < options else None
