"""RFC 8785 canonicalisation.

The ledger's hash chain is computed over this, and the chain is published so anyone can
recompute it. If this disagrees with a JavaScript or Go implementation by one character,
every independent verification fails and the transparency claim collapses.

The vectors below are from the RFC and from the properties it specifies. This is **not**
the complete official test suite - that is a separate distribution which is not vendored
here. What is asserted are the rules the RFC states, exercised on inputs a ledger entry
actually contains.
"""

from __future__ import annotations

import json

import pytest

from sarana_shared.crypto.canonical import (
    NotCanonicalisable,
    canonical_bytes,
    canonicalise,
)

# --------------------------------------------------------------------------------------
# Structure: sorting and whitespace
# --------------------------------------------------------------------------------------


def test_object_keys_are_sorted() -> None:
    assert canonicalise({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_there_is_no_whitespace() -> None:
    assert " " not in canonicalise({"a": [1, 2], "b": {"c": 3}})


def test_nested_objects_are_sorted_at_every_level() -> None:
    assert canonicalise({"b": {"z": 1, "a": 2}}) == '{"b":{"a":2,"z":1}}'


def test_array_order_is_preserved() -> None:
    """Arrays carry order as data. Sorting them would change the meaning."""
    assert canonicalise([3, 1, 2]) == "[3,1,2]"


def test_an_empty_object_and_array_are_canonical() -> None:
    assert canonicalise({}) == "{}"
    assert canonicalise([]) == "[]"


# --------------------------------------------------------------------------------------
# The one that catches implementations out: UTF-16 code unit ordering
# --------------------------------------------------------------------------------------


def test_keys_sort_by_utf16_code_unit_not_code_point() -> None:
    """The rule that separates a correct implementation from a nearly-correct one.

    U+10000 and above encode as surrogate pairs beginning 0xD800, so in UTF-16 order they
    come *before* U+E000..U+FFFF - the opposite of Python's default code-point ordering.

    An implementation using the host language's string comparison agrees on almost every
    input and disagrees on some emoji: rare enough to reach production, fatal when it does.
    """
    result = canonicalise({"\U0001f600": 1, "": 2})

    # The emoji (surrogate pair, 0xD83D...) sorts before U+E000.
    assert result.index("\U0001f600") < result.index("")


def test_ascii_keys_sort_as_expected() -> None:
    assert canonicalise({"A": 1, "a": 2, "0": 3}) == '{"0":3,"A":1,"a":2}'


def test_sinhala_and_tamil_keys_sort_deterministically() -> None:
    """Both scripts are below U+FFFF, so this is the straightforward case - asserted
    because these are the scripts this platform actually stores."""
    first = canonicalise({"ගං": 1, "வெ": 2})
    second = canonicalise({"வெ": 2, "ගං": 1})

    assert first == second


# --------------------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("\b", '"\\b"'),
        ("\t", '"\\t"'),
        ("\n", '"\\n"'),
        ("\f", '"\\f"'),
        ("\r", '"\\r"'),
        ('"', '"\\""'),
        ("\\", '"\\\\"'),
    ],
)
def test_short_escapes_are_used_where_they_exist(value: str, expected: str) -> None:
    assert canonicalise(value) == expected


def test_other_control_characters_use_the_four_digit_form() -> None:
    assert canonicalise("") == '"\\u0001"'


def test_non_ascii_characters_are_not_escaped() -> None:
    """RFC 8785 output is UTF-8. Escaping would be valid JSON and the wrong bytes."""
    assert canonicalise("ගංවතුර") == '"ගංවතුර"'


def test_the_solidus_is_not_escaped() -> None:
    """JSON permits \\/ but it is not the shortest form, so it must not be used."""
    assert canonicalise("a/b") == '"a/b"'


# --------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------


def test_integers_carry_no_decimal_point() -> None:
    assert canonicalise(1) == "1"
    assert canonicalise(-0) == "0"


def test_an_integral_float_serialises_as_an_integer() -> None:
    """ECMAScript prints 1.0 as "1".

    Python's "1.0" would make an integral float hash differently from the same integer,
    so two systems storing the same amount would produce different chains.
    """
    assert canonicalise(1.0) == "1"


def test_a_fractional_float_uses_its_shortest_round_trip_form() -> None:
    assert canonicalise(0.5) == "0.5"


def test_booleans_are_literals_not_numbers() -> None:
    """bool subclasses int in Python; JSON has separate literals."""
    assert canonicalise(True) == "true"
    assert canonicalise(False) == "false"
    assert canonicalise(None) == "null"


def test_nan_and_infinity_are_refused() -> None:
    """JSON cannot express them, so a hashed record must not contain one."""
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(NotCanonicalisable):
            canonicalise(value)


def test_an_unsupported_type_is_refused_rather_than_stringified() -> None:
    """Silently calling str() on an object would hash something nobody intended."""
    with pytest.raises(NotCanonicalisable):
        canonicalise({"when": object()})


# --------------------------------------------------------------------------------------
# Properties that matter to the chain
# --------------------------------------------------------------------------------------


def test_key_order_in_the_input_does_not_change_the_output() -> None:
    """The property the whole scheme exists for."""
    first = {"amount": 1, "beneficiary": "x", "seq": 3}
    second = {"seq": 3, "beneficiary": "x", "amount": 1}

    assert canonicalise(first) == canonicalise(second)


def test_the_output_is_valid_json_that_round_trips() -> None:
    entry = {"seq": 12, "amount_cents": 47_500_00, "categories": ["HOUSE_FULL"], "ok": True}

    assert json.loads(canonicalise(entry)) == entry


def test_canonical_bytes_are_utf8() -> None:
    assert canonical_bytes("ගං") == '"ගං"'.encode()


def test_a_realistic_ledger_entry_canonicalises_stably() -> None:
    """Two runs over the same entry must produce identical bytes, forever."""
    entry = {
        "seq": 4211,
        "entitlement_id": "01a04400-0000-7000-8000-000000000000",
        "amount_lkr_cents": 47_500_00,
        "payment_rail": "BANK_TRANSFER",
        "released_at": "2026-08-28T09:14:22+05:30",
        "trace": {"cost_schedule_version": "2026-03", "caps_applied": []},
    }

    assert canonical_bytes(entry) == canonical_bytes(dict(reversed(list(entry.items()))))
