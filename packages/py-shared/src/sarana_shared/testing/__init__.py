"""Shared pytest fixtures: a real Postgres via Testcontainers, an httpx test client, an
in-memory event bus, and a frozen clock.

Per docs/build-prompts/02-conventions.md: "Never mock the database — PostGIS and pgvector
behaviour is the thing most likely to be wrong." Every service's own conftest.py should
import from here rather than re-implementing these.
"""

from sarana_shared.testing.fixtures import (
    event_bus,
    frozen_clock,
    postgres_container,
    postgres_engine,
    postgres_session,
)

__all__ = [
    "event_bus",
    "frozen_clock",
    "postgres_container",
    "postgres_engine",
    "postgres_session",
]
