"""Request dependencies, and the one place a mock response is built.

`mock_json` is the only way a route in this service returns a body. Every response then
carries `X-Sarana-Mock: true` and a top-level `"source": "MOCK"` by construction rather
than by each of forty routes remembering to add them — and `sarana_shared.adapters.gov`
refuses any response that lacks them, so a route that bypassed this would fail at the first
client call rather than quietly serving unmarked data.

`SimulatedNow` is the other rule: **no route reads the wall clock.** It reads the simulated
clock, and it honours the chaos middleware's staleness flag, which is what makes the stale
injection possible at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any
from xml.etree import ElementTree
from xml.etree.ElementTree import Element

from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response

from gov_mock.state import MockState
from sarana_shared.adapters.gov.base import (
    MOCK_HEADER,
    MOCK_HEADER_VALUE,
    MOCK_SOURCE_FIELD,
    MOCK_SOURCE_VALUE,
    envelope,
)


def get_state(request: Request) -> MockState:
    """The service's shared state."""
    state: MockState = request.app.state.mock
    return state


StateDep = Annotated[MockState, Depends(get_state)]


def simulated_now(request: Request, state: StateDep) -> datetime:
    """The current simulated instant, wound back if chaos injected staleness.

    Every route takes this instead of calling `datetime.now()`. Two reasons: the mocks all
    have to agree about what time it is, and the stale injection has to have somewhere to
    apply. A route that read the wall clock would silently opt out of both.
    """
    now = state.clock.now()
    if getattr(request.state, "chaos_stale", False):
        return now - timedelta(hours=state.chaos.config.stale_window_hours)
    return now


SimulatedNowDep = Annotated[datetime, Depends(simulated_now)]


def simulated_hours(request: Request, state: StateDep) -> float:
    """Hours past landfall, wound back if chaos injected staleness.

    The generators are keyed on this rather than on an instant, so it is offered directly
    instead of every route recomputing it from `simulated_now`.
    """
    hours = state.clock.hours_since_landfall()
    if getattr(request.state, "chaos_stale", False):
        return hours - state.chaos.config.stale_window_hours
    return hours


SimulatedHoursDep = Annotated[float, Depends(simulated_hours)]


def mock_json(payload: dict[str, Any], *, status_code: int = 200) -> JSONResponse:
    """Build a mock JSON response.

    The envelope and the header come from `sarana_shared.adapters.gov.base`, which is also
    where the client that checks them lives. The two cannot drift apart because they read
    the same constants.
    """
    return JSONResponse(
        content=envelope(payload),
        status_code=status_code,
        headers={MOCK_HEADER: MOCK_HEADER_VALUE},
    )


def mock_xml(root: Element, *, status_code: int = 200) -> Response:
    """Build a mock XML response.

    XML has no envelope to hold `"source": "MOCK"`, so the marker goes on the root element
    as `source="MOCK"`. `require_mock_xml` on the client side checks exactly that, and
    stamping it here rather than in each builder means a new feed cannot forget it.
    """
    root.set(MOCK_SOURCE_FIELD, MOCK_SOURCE_VALUE)
    ElementTree.indent(root, space="  ")
    body = ElementTree.tostring(root, encoding="unicode", xml_declaration=False)
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?>\n{body}',
        status_code=status_code,
        media_type="application/xml",
        headers={MOCK_HEADER: MOCK_HEADER_VALUE},
    )
