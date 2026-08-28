"""Version 1 router for ledger-svc.

Order matters in one place. `/ledger/public` and `/ledger/anchors` are declared by the
ledger router before anything that could match `/ledger/{something}`, so a literal path is
never captured by a parameter. There is no such route today; the ordering is kept anyway,
because the day somebody adds `GET /ledger/{entry_id}` the public feed would start
returning 404 to every verifier and nothing would fail in CI.
"""

from __future__ import annotations

from fastapi import APIRouter

from ledger_svc.api.v1 import (
    anomalies,
    assessments,
    disbursements,
    entitlements,
    grievances,
    ledger,
)

router = APIRouter()
router.include_router(ledger.router)
router.include_router(assessments.router)
router.include_router(entitlements.router)
router.include_router(disbursements.router)
router.include_router(grievances.router)
router.include_router(anomalies.router)
