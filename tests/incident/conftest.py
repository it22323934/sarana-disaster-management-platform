"""Fixtures for the incident suite.

Reuses the migrated-database fixtures from the schema suite. The dispatch gate's last line
of defence is a database trigger, and testing that against anything but the real schema
would prove nothing at all.
"""

from __future__ import annotations

from tests.schema.conftest import (  # noqa: F401 - re-exported as fixtures
    REPO_ROOT,
    db,
    migrated_url,
    schema_engine,
)
