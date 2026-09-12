"""Every seeded template fits in two SMS segments, in all three languages.

Build file 14 requires this as a CI check, and the reason it is a release gate rather than a
metric is the asymmetry between the alphabets. Sinhala and Tamil are UCS-2 on the wire, so a
segment holds 70 characters where the English version gets 160 - and 67 per part once the
message is concatenated. A template that reads comfortably in English can be three segments
in Tamil.

Three segments is three times the cost, three times the queue on a gateway that is congested
by exactly the event being warned about, and three parts that can arrive out of order or not
at all. The community reading the Tamil version is then the one whose warning arrives last
and incomplete - the Ditwah failure arriving through a billing detail instead of through a
decision.

Checked with the **longest** parameter values in the seeded reference data, not typical
ones. A check that passed with "Kandy" and failed in production with a real division name
would be worse than no check, because it would be reassuring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarana_shared.domain import sms
from sarana_shared.domain.localised import REQUIRED_LOCALES
from tools import sms_segment_check
from tools.seed.templates import TEMPLATES

REFERENCE = Path("data/seed/reference")

CASES = [
    (template["code"], locale.value, template["body"][locale.value])
    for template in TEMPLATES
    for locale in REQUIRED_LOCALES
]


@pytest.mark.parametrize(
    ("code", "language", "body"), CASES, ids=[f"{code}-{lang}" for code, lang, _ in CASES]
)
def test_every_seeded_template_fits_in_two_segments(code: str, language: str, body: str) -> None:
    """The gate itself, one template and one language at a time.

    Parametrised rather than looped so a failure names the template and the language, which
    is what somebody shortening it needs to know.
    """
    values = sms_segment_check.worst_case_values(REFERENCE, language)
    rendered = sms_segment_check.render(body, values)
    counted = sms.count(rendered)

    assert counted.segments <= sms.MAX_SEGMENTS, (
        f"{code} [{language}] is {counted.as_sentence()}. Shorten it: an extra segment on "
        "a congested gateway is a warning that arrives in parts."
    )


def test_sinhala_and_tamil_are_measured_as_ucs2() -> None:
    """If this breaks, every other assertion in this file is measuring the wrong limit.

    One character outside GSM-7 moves the whole message to UCS-2 - there is no partial
    encoding - so a Sinhala template is 70 characters per segment however much of it is
    punctuation.
    """
    assert sms.encoding_for("ගංවතුර") is sms.SmsEncoding.UCS2
    assert sms.encoding_for("வெள்ளம்") is sms.SmsEncoding.UCS2
    assert sms.encoding_for("Flood warning") is sms.SmsEncoding.GSM7


def test_one_non_latin_character_moves_an_entire_message_to_ucs2() -> None:
    """The trap in a mixed-script template: it costs the same as a wholly Sinhala one."""
    assert sms.encoding_for("Flood warning for ගම්පොල") is sms.SmsEncoding.UCS2


def test_the_gsm7_extension_table_costs_two_units_per_character() -> None:
    """A euro sign or a brace is an escape plus a character on the wire."""
    assert sms.units_in("€") == 2
    assert sms.units_in("a") == 1


def test_segment_boundaries_are_where_the_standard_puts_them() -> None:
    assert sms.count("a" * 160).segments == 1
    assert sms.count("a" * 161).segments == 2
    assert sms.count("ක" * 70).segments == 1
    assert sms.count("ක" * 71).segments == 2
    assert sms.count("ක" * 134).segments == 2
    assert sms.count("ක" * 135).segments == 3


def test_a_character_outside_the_bmp_counts_as_the_two_units_it_occupies() -> None:
    """Counting Python characters would under-count and let a message through that the
    gateway then splits into one more part than was budgeted for."""
    assert sms.units_in("\U0001f300") == 2


def test_an_empty_message_is_one_segment_not_zero() -> None:
    """A gateway asked to send nothing still sends something, and reporting zero would let
    an empty template pass the check that exists to catch templates nobody looked at."""
    assert sms.count("").segments == 1


def test_the_checker_exits_zero_over_the_shipped_seed() -> None:
    """`python -m tools.sms_segment_check` is in build file 14's definition of done."""
    assert sms_segment_check.main([]) == 0


def test_the_checker_fails_a_template_that_is_too_long() -> None:
    """A gate that cannot fail is not a gate.

    The seed passes with headroom today, so the failing path would otherwise never be
    exercised until somebody wrote a long template and found the check silently broken.
    """
    overlong = [
        {
            "code": "TOO_LONG",
            "body": {locale.value: "ක" * 200 for locale in REQUIRED_LOCALES},
        }
    ]

    failures = [
        row
        for row in sms_segment_check.check(overlong, reference=REFERENCE)
        if row[2].segments > sms.MAX_SEGMENTS
    ]

    assert len(failures) == len(REQUIRED_LOCALES)


def test_the_checker_refuses_a_missing_seed_rather_than_reporting_a_pass() -> None:
    """A gate that reports zero templates as green is one that goes green the day somebody
    moves the seed."""
    assert sms_segment_check.main([str(REFERENCE / "does-not-exist.json")]) == 2


def test_worst_case_values_come_from_the_real_reference_data() -> None:
    """Not from a guess about what a division might be called."""
    rows = json.loads((REFERENCE / "gn_division.json").read_text(encoding="utf-8"))
    longest = max(len(str(row["name"]["ta"])) for row in rows)
    values = sms_segment_check.worst_case_values(REFERENCE, "ta")

    assert len(values["gn_division_name"]) == longest
