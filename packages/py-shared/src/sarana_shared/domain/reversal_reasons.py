"""Why a released payment came back, and what the household is told about it.

Shared because three services need the same answer and none of them may import another's
code:

  **gov-mock's payment rail** reports the reason.
  **ledger-svc** stores it against a CHECK constraint and puts the text in a grievance.
  **alerting-svc** renders that text into the SMS the household receives.

Keeping one copy is not tidiness. A family told one thing by SMS and something else at the
Divisional Secretariat counter is a family that stops believing either, and two copies of a
sentence like this drift the first time somebody improves the wording in one place.

**The text is an instruction, not a diagnosis.** `ACCOUNT_DORMANT` tells a family nothing.
"Visit your bank branch to reactivate it" tells them what to do on Monday morning. A test
asserts the English never contains the enum value, because the lazy version of this table
is the one that leaks a status code to a citizen.

Trilingual, without exception. Non-negotiable #2, on the path where it is easiest to forget
because the reader is one household rather than a district.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ReversalReason(StrEnum):
    """Why a rail returned money it had already accepted.

    Mirrored by the CHECK on `aid.disbursement_reversal.reason` and by the failure reasons
    `gov-mock`'s payment rail reports. `tests/ledger/test_vocabularies.py` asserts all
    three agree, because a value the schema rejects is a 500 at the exact moment a
    household's payment has just bounced.
    """

    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    ACCOUNT_DORMANT = "ACCOUNT_DORMANT"
    NAME_MISMATCH = "NAME_MISMATCH"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    RAIL_RETURNED = "RAIL_RETURNED"
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    ADMINISTRATIVE_ERROR = "ADMINISTRATIVE_ERROR"

    @property
    def needs_new_bank_details(self) -> bool:
        """Whether fixing this means the household supplying a different account.

        The distinction an officer needs first: these cannot be retried at all until
        somebody speaks to the household, while the others may resolve on a second attempt.
        """
        return self in {
            ReversalReason.ACCOUNT_CLOSED,
            ReversalReason.INVALID_ACCOUNT,
            ReversalReason.NAME_MISMATCH,
        }


REASON_TEXT: Final[dict[ReversalReason, dict[str, str]]] = {
    ReversalReason.ACCOUNT_CLOSED: {
        "si": "ඔබගේ බැංකු ගිණුම වසා ඇති බැවින් ගෙවීම ආපසු ලැබුණි. නව ගිණුම් විස්තර සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "உங்கள் வங்கிக் கணக்கு மூடப்பட்டதால் பணம் திருப்பி அனுப்பப்பட்டது. புதிய "
        "கணக்கு விவரங்களுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the bank account is closed. Please take "
        "new account details to the Divisional Secretariat.",
    },
    ReversalReason.ACCOUNT_DORMANT: {
        "si": "ඔබගේ බැංකු ගිණුම නිෂ්ක්‍රීය බැවින් ගෙවීම ආපසු ලැබුණි. ගිණුම නැවත සක්‍රීය කිරීමට ඔබගේ බැංකු ශාඛාවට යන්න.",
        "ta": "உங்கள் வங்கிக் கணக்கு செயலிழந்துள்ளதால் பணம் திருப்பி அனுப்பப்பட்டது. "
        "கணக்கை மீண்டும் இயக்க உங்கள் வங்கிக் கிளைக்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the bank account is dormant. Please visit "
        "your bank branch to reactivate it.",
    },
    ReversalReason.NAME_MISMATCH: {
        "si": "බැංකු ගිණුමේ නම ලේඛනගත නමට නොගැලපෙන බැවින් ගෙවීම ආපසු ලැබුණි. "
        "හැඳුනුම්පත සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "வங்கிக் கணக்கின் பெயர் பதிவுப் பெயருடன் பொருந்தாததால் பணம் திருப்பி "
        "அனுப்பப்பட்டது. அடையாள அட்டையுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The payment was returned because the account name does not match the "
        "registered name. Please take your identity card to the Divisional Secretariat.",
    },
    ReversalReason.INVALID_ACCOUNT: {
        "si": "බැංකු ගිණුම් අංකය වලංගු නොවේ. නිවැරදි විස්තර සමඟ ප්‍රාදේශීය ලේකම් කාර්යාලයට යන්න.",
        "ta": "வங்கிக் கணக்கு எண் செல்லுபடியாகாது. சரியான விவரங்களுடன் பிரதேச செயலகத்திற்குச் செல்லுங்கள்.",
        "en": "The bank account number is not valid. Please take the correct details to "
        "the Divisional Secretariat.",
    },
    ReversalReason.LIMIT_EXCEEDED: {
        "si": "ගිණුමේ සීමාව ඉක්මවා ගිය බැවින් ගෙවීම ආපසු ලැබුණි. එය නැවත යවනු ලැබේ; ඔබ කිසිවක් කළ යුතු නැත.",
        "ta": "கணக்கு வரம்பு மீறியதால் பணம் திருப்பி அனுப்பப்பட்டது. அது மீண்டும் "
        "அனுப்பப்படும்; நீங்கள் எதுவும் செய்யத் தேவையில்லை.",
        "en": "The payment was returned because an account limit was exceeded. It will be "
        "sent again; you do not need to do anything.",
    },
    ReversalReason.RAIL_RETURNED: {
        "si": "බැංකුව ගෙවීම ආපසු එවා ඇත. හේතුව සොයා බලමින් සිටී; ඔබට නැවත දැනුම් දෙනු ලැබේ.",
        "ta": "வங்கி பணத்தைத் திருப்பி அனுப்பியுள்ளது. காரணம் ஆராயப்படுகிறது; உங்களுக்கு மீண்டும் தெரிவிக்கப்படும்.",
        "en": "The bank returned the payment. The reason is being investigated and you "
        "will be contacted again.",
    },
    ReversalReason.DUPLICATE_PAYMENT: {
        "si": "මෙම ගෙවීම දෙවරක් යවා ඇති බැවින් එක් ගෙවීමක් ආපසු ගන්නා ලදී. ඔබට හිමි මුදල වෙනස් වී නැත.",
        "ta": "இந்தப் பணம் இரண்டு முறை அனுப்பப்பட்டதால் ஒன்று திரும்பப் பெறப்பட்டது. உங்களுக்கு உரிய தொகை மாறவில்லை.",
        "en": "This payment was sent twice, so one has been reversed. The amount you are "
        "owed has not changed.",
    },
    ReversalReason.ADMINISTRATIVE_ERROR: {
        "si": "පරිපාලන දෝෂයක් හේතුවෙන් ගෙවීම ආපසු ගන්නා ලදී. නිවැරදි කිරීමෙන් පසු ඔබට දැනුම් දෙනු ලැබේ.",
        "ta": "நிர்வாகப் பிழை காரணமாக பணம் திரும்பப் பெறப்பட்டது. திருத்தப்பட்ட பின் உங்களுக்குத் தெரிவிக்கப்படும்.",
        "en": "The payment was reversed because of an administrative error. You will be "
        "contacted once it is corrected.",
    },
}

# What to say when the reason is one this build does not recognise - an older service
# publishing a value added since, most likely. Unspecific but true, and never silence: the
# household still needs to know the money came back.
UNKNOWN_REASON_TEXT: Final[dict[str, str]] = {
    "si": "ගෙවීම ආපසු ලැබුණි. හේතුව සොයා බලමින් සිටී; ඔබට නැවත දැනුම් දෙනු ලැබේ.",
    "ta": "பணம் திருப்பி அனுப்பப்பட்டது. காரணம் ஆராயப்படுகிறது; உங்களுக்கு மீண்டும் தெரிவிக்கப்படும்.",
    "en": "The payment was returned. The reason is being investigated and you will be "
    "contacted again.",
}


def reason_text(reason: str, language: str) -> str:
    """What to tell a household, in their language.

    Never raises and never returns an empty string. A reason this build does not know is
    still a payment that came back, and refusing to render it would mean the household
    hears nothing at all.
    """
    try:
        known = ReversalReason(reason)
    except ValueError:
        return UNKNOWN_REASON_TEXT.get(language, UNKNOWN_REASON_TEXT["en"])

    text = REASON_TEXT[known]
    return text.get(language, text["en"])
