"""Structured logging and PII redaction.

Structured JSON only. Required keys on every line: ts, level, service, event,
correlation_id.

Never log: NIC numbers, full names, phone numbers, exact household coordinates, bank
details. `redact()` is a deny-list plus a regex sweep, applied as a structlog processor
so it catches values that reach the logger through any path, not only the ones a
developer remembered to wrap.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, Final

import structlog
from structlog.types import EventDict, Processor

REDACTED: Final = "[REDACTED]"

# Key names whose values are never safe to log, matched case-insensitively as substrings
# so `applicant_nic`, `nic_number` and `NIC` are all caught.
DENY_KEY_SUBSTRINGS: Final[tuple[str, ...]] = (
    "nic",
    "national_id",
    "passport",
    "phone",
    "msisdn",
    "mobile",
    "full_name",
    "given_name",
    "surname",
    "household_name",
    "address",
    "bank_account",
    "account_number",
    "iban",
    "sort_code",
    "beneficiary",
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "private_key",
    "otp",
    "email",
    "dob",
    "date_of_birth",
    "lat",
    "lon",
    "latitude",
    "longitude",
    "coordinates",
)

# Keys that look sensitive by substring but are safe and operationally necessary.
ALLOW_KEYS: Final[frozenset[str]] = frozenset(
    {
        "correlation_id",
        "token_kind",
        "phone_channel",
        "address_level",
        "latency_ms",
    }
)

# Sri Lanka NIC: legacy nine digits plus V or X, and the 12-digit form issued since 2016.
NIC_PATTERN: Final = re.compile(r"\b(?:\d{9}[VXvx]|\d{12})\b")

# Sri Lanka mobile and landline, local or +94 international form.
PHONE_PATTERN: Final = re.compile(r"(?:\+94|\b0)[\s-]?\d{2}[\s-]?\d{3}[\s-]?\d{4}\b")

# A bare decimal pair that looks like a Sri Lanka coordinate.
COORD_PATTERN: Final = re.compile(r"\b[5-9]\.\d{4,}\s*,\s*(?:7[9]|8[0-2])\.\d{4,}\b")

_TEXT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (NIC_PATTERN, PHONE_PATTERN, COORD_PATTERN)

MAX_REDACT_DEPTH: Final = 8


def _is_denied(key: str) -> bool:
    lowered = key.lower()
    if lowered in ALLOW_KEYS:
        return False
    return any(fragment in lowered for fragment in DENY_KEY_SUBSTRINGS)


def redact_text(value: str) -> str:
    """Sweep a free-text value for NIC, phone and coordinate patterns."""
    for pattern in _TEXT_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Return `value` with personal data removed.

    Recurses into dicts, lists and tuples. Depth-limited: a cyclic or pathologically
    nested structure degrades to a marker rather than hanging the logging call.
    """
    if _depth > MAX_REDACT_DEPTH:
        return "[TRUNCATED]"

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_denied(str(key)) else redact(item, _depth=_depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        rendered = [redact(item, _depth=_depth + 1) for item in value]
        return tuple(rendered) if isinstance(value, tuple) else rendered
    return value


def redaction_processor(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor applying `redact` to every bound value."""
    return {
        key: REDACTED if _is_denied(str(key)) else redact(value)
        for key, value in event_dict.items()
    }


def correlation_processor(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
    """Attach the ambient correlation ID to every line that does not carry one."""
    from sarana_shared.domain.ids import get_correlation_id

    if "correlation_id" not in event_dict:
        current = get_correlation_id()
        if current is not None:
            event_dict["correlation_id"] = current
    return event_dict


def service_processor(service: str) -> Processor:
    """Build a processor stamping the service name on every line."""

    def processor(_logger: object, _method_name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        return event_dict

    return processor


def configure_logging(
    *,
    service: str,
    level: str = "INFO",
    json_output: bool = True,
) -> None:
    """Configure structlog and the stdlib logging bridge for a service.

    `json_output=False` gives a human-readable console renderer for local development.
    Redaction runs in both modes - there is no development mode that logs a NIC.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        service_processor(service),
        correlation_processor,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redaction_processor,
    ]

    renderer: Processor = (
        structlog.processors.JSONRenderer(sort_keys=True)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers - uvicorn, sqlalchemy, httpx - through the same pipeline, so
    # a third-party library cannot emit an unredacted line.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)

    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine", "httpx"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Prefer this over `structlog.get_logger` in services."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
