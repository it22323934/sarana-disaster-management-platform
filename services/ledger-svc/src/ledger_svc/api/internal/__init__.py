"""Service-to-service endpoints for ledger-svc.

Mounted under `/internal/v1`, reachable only inside the cluster network, and still
authenticated: an internal path is not a trusted one.
"""

from __future__ import annotations

from fastapi import APIRouter

from ledger_svc.api.internal import confirmations

router = APIRouter()
router.include_router(confirmations.router)
