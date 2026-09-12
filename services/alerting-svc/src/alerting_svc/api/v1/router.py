"""Version 1 router for alerting-svc."""

from __future__ import annotations

from fastapi import APIRouter

from alerting_svc.api.v1 import alerts, coverage, public, templates

router = APIRouter()
router.include_router(alerts.router)
router.include_router(templates.router)
router.include_router(coverage.router)
# The public alert history. Mounted under /public, which the auth middleware treats as
# anonymous by prefix, so it needs no per-route exemption.
router.include_router(public.router)
