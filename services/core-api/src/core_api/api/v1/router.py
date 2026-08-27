"""Version 1 router for core-api.

REST, plural collection paths, cursor pagination, RFC 9457 Problem Details on error. The
`/api/v1` prefix is applied by the app factory, so a router here declares only its own
collection path.
"""

from __future__ import annotations

from fastapi import APIRouter

from core_api.api.v1 import admin, admin_events, audit, auth, meta, rg

router = APIRouter()
router.include_router(auth.router)
router.include_router(meta.router)
# Both of these carry the `/admin` prefix: `admin` holds the hierarchy reads, and
# `admin_events` the replay and dead-letter operator endpoints. Distinct paths under a
# shared prefix, kept in separate modules because they answer to different scopes.
router.include_router(admin.router)
router.include_router(admin_events.router)
router.include_router(rg.router)
router.include_router(audit.router)
