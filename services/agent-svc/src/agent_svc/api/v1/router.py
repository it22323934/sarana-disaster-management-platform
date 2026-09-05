"""Version 1 router for agent-svc.

Routers for each resource are mounted here. The prefix `/api/v1` is applied by the app
factory, so a router in this package declares only its own collection path.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_svc.api.v1 import agents, forecasts, hazard_events

router = APIRouter()
router.include_router(agents.router)
router.include_router(hazard_events.router)
router.include_router(forecasts.router)
