"""Schema constants for the four schemas core-api owns.

`admin` (administrative hierarchy, households, users, roles), `resilience` (the
Resilience Graph), `audit` (the append-only action log), and core-api's slice of
`outbox`.

Constraint builders live in `sarana_shared.db.constraints`: a trilingual CHECK spelled
slightly differently in five schemas is five chances for one of them to be wrong.
"""

from __future__ import annotations

from typing import Final

ADMIN_SCHEMA: Final = "admin"
RESILIENCE_SCHEMA: Final = "resilience"
AUDIT_SCHEMA: Final = "audit"

# Fixed by the master context: text-embedding-3-large at 1024 dimensions. Changing
# this is a migration and a re-embedding job, not a config change.
EMBEDDING_DIMENSIONS: Final = 1024
