"""Reference data: every enum and taxonomy the clients render, in all three languages.

One endpoint so that the console, the public dashboard and both mobile apps draw their
dropdowns from the same list. Four hardcoded copies of a status enum is four chances for
one of them to be missing the status that matters during an incident.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from core_api.cache import REFERENCE_MAX_AGE, apply_cache_headers, etag_for, matches, not_modified
from sarana_shared.domain.taxonomy import reference_catalogue

router = APIRouter(prefix="/meta", tags=["reference"])


@router.get("/reference")
async def get_reference(request: Request, response: Response) -> Any:
    """Every taxonomy with trilingual labels, ETagged.

    Deliberately anonymous. These are enum labels, not data about anyone, and the public
    dashboard and the login screen both need them before there is a token to present.
    Requiring auth here would mean the sign-in page could not render its own language
    picker.

    Taxonomies sit at the top level rather than under a wrapper key, so a client reads
    `.hazard_types` directly.
    """
    payload = reference_catalogue()

    tag = etag_for(payload)
    if matches(request, tag):
        return not_modified(tag, max_age=REFERENCE_MAX_AGE)

    apply_cache_headers(response, etag=tag, max_age=REFERENCE_MAX_AGE)
    return payload
