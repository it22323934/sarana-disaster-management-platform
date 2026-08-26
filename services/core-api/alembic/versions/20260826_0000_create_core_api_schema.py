"""create the core-api schemas

Schema creation only. Domain tables arrive with the data model.

Revision ID: core_api_0001
Revises:
Created: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_api_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS: tuple[str, ...] = ("reference", "resilience")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    # RESTRICT, never CASCADE: a downgrade must fail loudly rather than silently drop
    # tables another migration created.
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
