"""CAP 1.2 alert documents — the implementation now lives in `sarana_shared.domain.cap`.

It moved there when the warning agent (file 14) needed to build and validate the same
document before handing it to this service. Two CAP validators disagreeing about whether a
warning is dispatchable is not a disagreement anybody would find until it mattered, so
there is one, and it sits where both services can reach it.

Re-exported rather than replaced at every call site: `from alerting_svc.domain import cap`
reads correctly in a service whose whole job is alerts, and the indirection is one line
that says where the rules actually are.
"""

from __future__ import annotations

from sarana_shared.domain.cap import (
    CAP_LANGUAGES,
    CAP_NAMESPACE,
    CERTAINTIES,
    COLOMBO_OFFSET,
    GEOCODE_VALUE_NAME,
    MAX_DOCUMENT_BYTES,
    MAX_POLYGON_POINTS,
    MSG_TYPES,
    SCOPES,
    SEVERITIES,
    STATUSES,
    URGENCIES,
    Area,
    CapAlert,
    CapInvalid,
    build,
    cap_case,
    parse_problems,
    to_xml,
    validate,
)

__all__ = [
    "CAP_LANGUAGES",
    "CAP_NAMESPACE",
    "CERTAINTIES",
    "COLOMBO_OFFSET",
    "GEOCODE_VALUE_NAME",
    "MAX_DOCUMENT_BYTES",
    "MAX_POLYGON_POINTS",
    "MSG_TYPES",
    "SCOPES",
    "SEVERITIES",
    "STATUSES",
    "URGENCIES",
    "Area",
    "CapAlert",
    "CapInvalid",
    "build",
    "cap_case",
    "parse_problems",
    "to_xml",
    "validate",
]
