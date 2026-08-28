"""Fixtures for the ledger suite.

Reuses the migrated-database fixtures from the schema suite. The chain's enforcement is a
database trigger, and testing it against anything but the real schema would prove nothing.
"""

from __future__ import annotations

from tests.schema.conftest import (  # noqa: F401 - re-exported as fixtures
    REPO_ROOT,
    db,
    migrated_url,
    schema_engine,
)
