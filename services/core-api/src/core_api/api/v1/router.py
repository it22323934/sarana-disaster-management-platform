"""Version 1 router for core-api.

REST, plural collection paths, cursor pagination, RFC 9457 Problem Details on error. The
`/api/v1` prefix is applied by the app factory, so a router here declares only its own
collection path.
"""

from __future__ import annotations

from fastapi import APIRouter

from core_api.api.v1 import admin_events, auth

router = APIRouter()
router.include_router(auth.router)
router.include_router(admin_events.router)
