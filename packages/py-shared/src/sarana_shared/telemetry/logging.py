"""Structured JSON logging + redact() — the deny-list and regex sweep that keeps NIC
numbers, phone numbers, full names, exact coordinates, and bank details out of every
log line, per docs/build-prompts/02-conventions.md and 27-security-and-guardrails.md.

Required keys on every line: ts, level, service, event, correlation_id (per
docs/build-prompts/26-observability.md).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog

_DENY_KEYS = frozenset(
    {
        "nic",
        "nic_number",
        "full_name",
        "name",
        "head_name",
        "phone",
        "phone_number",
        "msisdn",
        "mobile",
        "bank_account",
        "bank_details",
        "auth_token",
        "authorization",
        "password",
        "totp_secret",
        "coordinates",
        "lat",
        "lng",
        "latitude",
        "longitude",
    }
)

# Sri Lankan NIC: 9 digits + V/X (old format) or 12 digits (new format).
_NIC_PATTERN = re.compile(r"\b(\d{9}[VvXx]|\d{12})\b")
# +94 or 0-prefixed Sri Lankan mobile numbers.
_PHONE_PATTERN = re.compile(r"\b(?:\+?94|0)7\d{8}\b")

_REDACTED = "[REDACTED]"


def _redact_string(value: str) -> str:
    value = _NIC_PATTERN.sub(_REDACTED, value)
    value = _PHONE_PATTERN.sub(_REDACTED, value)
    return value


def redact(value: Any) -> Any:
    """Recursively redact a log payload. Applied at the logging handler, not left to
    callers to remember — see configure_logging's processor chain below."""
    if isinstance(value, dict):
        return {k: (_REDACTED if k.lower() in _DENY_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_processor(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    # redact() is recursively typed as Any -> Any (it processes dict/list/str/other
    # branches at runtime); cast the top-level call site since we know the shape here.
    return cast(Mapping[str, Any], redact(dict(event_dict)))


def configure_logging(*, service: str, level: str = "INFO") -> None:
    """Call once, at process startup, in every service's main.py."""
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="ts"),
            structlog.stdlib.add_logger_name,
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(**initial_context: Any) -> structlog.typing.FilteringBoundLogger:
    # structlog.get_logger()'s own return type is Any; cast to the type we configure
    # `wrapper_class` to in configure_logging above.
    return cast(structlog.typing.FilteringBoundLogger, structlog.get_logger(**initial_context))
