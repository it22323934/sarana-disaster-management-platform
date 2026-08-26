"""Version 1 router for alerting-svc.

Routers for each resource are mounted here. The prefix `/api/v1` is applied by the app
factory, so a router in this package declares only its own collection path.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
