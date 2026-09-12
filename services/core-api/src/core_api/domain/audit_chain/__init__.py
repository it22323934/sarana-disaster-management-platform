"""The append-only, hash-chained record of who did what."""

from __future__ import annotations

from core_api.domain.audit_chain.entries import search_entries, write_entry
from core_api.domain.audit_chain.verify import (
    Divergence,
    VerificationResult,
    chain_bounds,
    verify_range,
)

__all__ = [
    "Divergence",
    "VerificationResult",
    "chain_bounds",
    "search_entries",
    "verify_range",
    "write_entry",
]
