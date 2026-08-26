"""ledger-svc — the Transparent Aid Ledger: assessments, entitlements, approvals,
hash-chained disbursement, grievances.

This is the differentiator (docs/build-prompts/10-aid-ledger-service.md) — the service
with the highest bar for correctness in the platform. mypy runs in --strict mode against
this package (docs/build-prompts/02-conventions.md: "85% coverage on ledger-svc and
anything touching money"). This scaffold only provides the FastAPI app factory, config,
and health/readiness endpoints.
"""
