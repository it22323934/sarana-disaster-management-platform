"""Version 1 router for alerting-svc."""

from __future__ import annotations

from fastapi import APIRouter

from alerting_svc.api.v1 import alerts, coverage, templates

router = APIRouter()
router.include_router(alerts.router)
router.include_router(templates.router)
router.include_router(coverage.router)
