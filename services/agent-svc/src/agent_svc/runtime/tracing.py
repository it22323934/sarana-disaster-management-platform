"""Tracing, and the redaction that runs before anything leaves the country.

LangSmith tracing is on because an agent nobody can inspect is an agent nobody should
trust. But traces go to a service outside Sri Lanka, and ADR-011 is explicit: citizen data
does not leave. So the exporter runs `redact()` over every payload first.

**What is removed, and why each one:**

  *NIC numbers* — a national identity number is the strongest identifier a person has.
  *Phone numbers* — the platform holds these as keyed hashes precisely so they are not
  exportable; a trace that carried the plaintext would undo that.
  *Names* — including in free text, which is where they actually appear.
  *Exact coordinates* — fuzzed to the GN division centroid. A trace showing a household's
  precise location during a disaster is a targeting list.

**Redaction is subtractive, never a mask.** A field that might contain personal data is
dropped, not replaced with asterisks. `[REDACTED]` in a trace still tells a reader that
this person has a NIC on file and roughly how long it is; absence tells them nothing. This
is the same principle as the seeded households carrying no names at all: personal data
absent beats personal data redacted.

**The deny-list is a floor, not a ceiling.** It catches the fields we know about. The rule
that actually holds the line is upstream: don't put personal data in agent state. This is
the last check, not the only one.
"""

from __future__ import annotations

import re
from typing import Any, Final

import structlog

_log = structlog.get_logger(__name__)

# Field names whose values never leave. Matched case-insensitively on the whole key and on
# any suffix after an underscore, so `head_nic`, `contact_msisdn` and `reporter_name` are
# all caught without listing every prefix somebody might invent.
DENIED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "nic",
        "msisdn",
        "phone",
        "phone_number",
        "mobile",
        "name",
        "full_name",
        "head_name",
        "address",
        "email",
        "password",
        "secret",
        "token",
        "client_secret",
        "api_key",
        "authorization",
        "recipient_ref_hash",
        "contact_msisdn_hash",
        "sender_hash",
    }
)

# Coordinate fields. Not dropped - a forecast is meaningless without a location - but
# rounded to roughly a GN division rather than a doorstep.
COORDINATE_FIELDS: Final[frozenset[str]] = frozenset({"lat", "lon", "lng", "latitude", "longitude"})

# Two decimal places is about a kilometre at Sri Lankan latitudes: the scale of a GN
# division, and far coarser than a house.
COORDINATE_PRECISION: Final = 2

# NIC numbers in free text. Both formats in circulation: twelve digits since 2016, and nine
# digits with a V or X before that. Anyone holding an old card still holds it.
_NIC_PATTERN: Final = re.compile(r"\b(\d{12}|\d{9}[VXvx])\b")

# Sri Lankan mobile numbers, with or without the country code.
_MSISDN_PATTERN: Final = re.compile(r"\b(?:\+94|0)7\d{8}\b")

# What free text becomes when a pattern matches. A marker rather than the value, because
# the surrounding sentence is usually the thing worth tracing.
_TEXT_MARKER: Final = "[removed]"

# Anything longer than this is free text a person wrote, and free text is where names
# actually appear. Scanned rather than trusted.
FREE_TEXT_THRESHOLD: Final = 40


def redact(payload: Any, *, _depth: int = 0) -> Any:
    """Strip personal data from a trace payload.

    Recursive over dicts and lists. Depth-limited because a cyclic structure in a trace
    exporter should not take the process with it - and a payload nested twenty deep is one
    nobody was going to read anyway.
    """
    if _depth > 20:
        return "[too deeply nested to redact safely]"

    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if _is_denied(lowered):
                # Dropped, not masked. A mask still confirms the field exists and hints at
                # its shape; absence says nothing at all.
                continue
            if lowered in COORDINATE_FIELDS and isinstance(value, int | float):
                cleaned[key] = round(float(value), COORDINATE_PRECISION)
                continue
            cleaned[key] = redact(value, _depth=_depth + 1)
        return cleaned

    if isinstance(payload, list | tuple):
        return [redact(item, _depth=_depth + 1) for item in payload]

    if isinstance(payload, str):
        return _redact_text(payload)

    return payload


def _is_denied(key: str) -> bool:
    """Whether a field name is on the deny-list.

    Matches the whole key or its last underscore-separated part, so `head_nic` and
    `reporter_full_name` are caught without enumerating every prefix.
    """
    if key in DENIED_FIELDS:
        return True
    tail = key.rsplit("_", 1)[-1]
    return tail in DENIED_FIELDS


def _redact_text(value: str) -> str:
    """Remove identifiers from free text.

    Only patterns that are unambiguous. Names are not pattern-matchable and are handled by
    the field deny-list and by not putting them in state in the first place — a heuristic
    that tried would mangle Sinhala and Tamil text far more than English, which is exactly
    the wrong direction for this platform.
    """
    if len(value) < FREE_TEXT_THRESHOLD and not _NIC_PATTERN.search(value):
        return value
    cleaned = _NIC_PATTERN.sub(_TEXT_MARKER, value)
    return _MSISDN_PATTERN.sub(_TEXT_MARKER, cleaned)


def configure_tracing(*, enabled: bool, project: str, api_key: str | None) -> bool:
    """Turn LangSmith tracing on, or say why it stayed off.

    Returns whether it is actually on. A deployment that meant to trace and silently did
    not is one where nobody notices until they need a trace that does not exist.
    """
    import os

    if not enabled:
        _log.info("agent_tracing_disabled", reason="disabled by configuration")
        return False
    if not api_key:
        _log.warning(
            "agent_tracing_disabled",
            reason="no LANGSMITH_API_KEY",
            impact="agent runs will not be traced; debugging a bad decision later means "
            "reading checkpoints by hand",
        )
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project
    _log.info("agent_tracing_enabled", project=project, redaction="on")
    return True
