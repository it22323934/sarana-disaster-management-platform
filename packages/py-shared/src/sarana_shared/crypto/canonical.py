"""RFC 8785 JSON Canonicalization Scheme.

The aid ledger's hash chain is computed over this. A chain over `json.dumps` output
verifies for nobody: two systems that serialise the same object with different key order,
different spacing, or a different float representation produce different hashes, and the
whole point of publishing the chain is that a journalist with their own tooling can
recompute it and get the same answer.

The scheme, in full:

  1. Object members are sorted by key, comparing **UTF-16 code units** — not Unicode code
     points, and not the host language's default string ordering.
  2. No whitespace anywhere.
  3. Strings use the shortest escaping JSON allows.
  4. Numbers use ECMAScript's `Number::toString`, which is the shortest representation
     that round-trips.

Point 1 is the one that bites. Python compares strings by code point, and for characters
above U+FFFF the two orders differ: those are encoded in UTF-16 as surrogate pairs
starting at 0xD800, so they sort *before* U+E000..U+FFFF rather than after. An
implementation that used Python's default ordering would agree with a JavaScript
verifier on almost every input and disagree on some emoji, which is the worst possible
failure mode — rare enough to reach production, fatal when it happens.
"""

from __future__ import annotations

import math
from typing import Any, Final

# Characters JSON requires be escaped, with their shortest forms.
_SHORT_ESCAPES: Final[dict[int, str]] = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


class NotCanonicalisable(ValueError):
    """The value has no RFC 8785 representation.

    NaN and the infinities are the usual cause. JSON has no syntax for them, so a ledger
    entry containing one cannot be canonicalised - and must therefore not exist.
    """


def _utf16_key(text: str) -> tuple[int, ...]:
    """A sort key matching UTF-16 code unit order.

    Encoding to UTF-16BE and reading back as 16-bit units gives exactly the comparison
    RFC 8785 specifies, surrogate pairs included, without hand-rolling the surrogate
    arithmetic.
    """
    encoded = text.encode("utf-16-be", errors="surrogatepass")
    return tuple((encoded[index] << 8) | encoded[index + 1] for index in range(0, len(encoded), 2))


def _serialise_string(value: str) -> str:
    """A JSON string with the minimum escaping the standard allows."""
    out = ['"']
    for character in value:
        code = ord(character)
        if code in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[code])
        elif code < 0x20:
            # Control characters with no short form take the lower-case \u00xx form.
            out.append(f"\\u{code:04x}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def _serialise_number(value: int | float) -> str:
    """ECMAScript `Number::toString`.

    Integers are emitted without a decimal point; everything else uses Python's `repr`,
    which is the shortest round-tripping form and agrees with ECMAScript across the range
    a currency ledger uses. The exponent forms differ from ECMAScript for very large and
    very small magnitudes, which is why money is stored as integer cents and never as a
    float - see `sarana_shared.domain.money`.
    """
    if isinstance(value, bool):
        # bool is a subclass of int in Python; JSON has separate literals for it.
        raise NotCanonicalisable("booleans are literals, not numbers")

    if isinstance(value, int):
        return str(value)

    if math.isnan(value) or math.isinf(value):
        raise NotCanonicalisable(
            f"{value!r} has no JSON representation, so it cannot appear in a hashed record"
        )

    if value == int(value) and abs(value) < 1e21:
        # ECMAScript prints 1.0 as "1". Preserving Python's "1.0" here would make an
        # integral float hash differently from the same integer.
        return str(int(value))

    return repr(value)


def _serialise(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _serialise_string(value)
    if isinstance(value, int | float):
        return _serialise_number(value)
    if isinstance(value, list | tuple):
        # Array order is data, never sorted.
        return "[" + ",".join(_serialise(item) for item in value) + "]"
    if isinstance(value, dict):
        members = sorted(value.items(), key=lambda item: _utf16_key(str(item[0])))
        return (
            "{"
            + ",".join(f"{_serialise_string(str(key))}:{_serialise(item)}" for key, item in members)
            + "}"
        )
    raise NotCanonicalisable(
        f"{type(value).__name__} has no JSON representation; convert it before hashing"
    )


def canonicalise(value: Any) -> str:
    """The RFC 8785 canonical form of a JSON-compatible value.

    Raises:
        NotCanonicalisable: for NaN, the infinities, or any type JSON cannot express.
    """
    return _serialise(value)


def canonical_bytes(value: Any) -> bytes:
    """The canonical form as UTF-8, which is what gets hashed."""
    return canonicalise(value).encode("utf-8")
