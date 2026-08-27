"""Version 1 router for incident-svc.

Routers for each resource are mounted here. The prefix `/api/v1` is applied by the app
factory, so a router in this package declares only its own collection path.
"""

from __future__ import annotations

from fastapi import APIRouter

from incident_svc.api.v1 import dispatch, incidents, reports, review

router = APIRouter()
router.include_router(reports.router)
router.include_router(incidents.router)
router.include_router(dispatch.router)
router.include_router(review.router)
