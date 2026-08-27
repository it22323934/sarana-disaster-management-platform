"""ETag and Cache-Control helpers for the read endpoints.

The hierarchy is 14,022 GN divisions that change on a census cycle. Serving it from the
database on every request would make the reference data the most expensive thing in the
platform, so these endpoints are cached hard and revalidated with an ETag.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from fastapi import Request, Response

# The hierarchy changes roughly never; an hour of staleness costs nothing and removes
# 14,022 rows from the hot path.
HIERARCHY_MAX_AGE: Final = 3600
REFERENCE_MAX_AGE: Final = 3600

STALE_HEADER: Final = "X-Sarana-Stale"


def etag_for(payload: Any) -> str:
    """A strong ETag over a JSON-serialisable payload.

    Sorted keys and separators fixed, so the same data always produces the same tag
    regardless of dict ordering. A tag that changes when the data has not would defeat
    the point of sending one.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f'"{digest[:32]}"'


def matches(request: Request, etag: str) -> bool:
    """Whether the client already holds this exact representation.

    Handles the `If-None-Match: *` wildcard and comma-separated lists, and tolerates a
    `W/` weak prefix on the client's tags.
    """
    header = request.headers.get("if-none-match")
    if not header:
        return False
    candidates = {token.strip() for token in header.split(",") if token.strip()}
    if "*" in candidates:
        return True
    normalised = {token[2:] if token.startswith("W/") else token for token in candidates}
    return etag in normalised


def apply_cache_headers(
    response: Response,
    *,
    etag: str,
    max_age: int,
    stale: bool = False,
    public: bool = True,
) -> None:
    """Set the caching headers for a read response.

    `stale` marks a response served from an expired cache entry because the database was
    unreachable. It is a header rather than an error so that a client can render the data
    and say so, which is the whole point of degrading instead of failing.
    """
    visibility = "public" if public else "private"
    response.headers["Cache-Control"] = f"{visibility}, max-age={max_age}"
    response.headers["ETag"] = etag
    if stale:
        response.headers[STALE_HEADER] = "true"
        # A stale body must not be written into a shared cache as if it were current.
        response.headers["Cache-Control"] = f"{visibility}, max-age=0, must-revalidate"


def not_modified(etag: str, *, max_age: int) -> Response:
    """A 304 carrying the headers a conditional request needs to stay useful."""
    response = Response(status_code=304)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response
