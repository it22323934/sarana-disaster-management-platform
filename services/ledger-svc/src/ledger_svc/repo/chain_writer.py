"""Appending to a published hash chain.

The trigger requires the caller to supply both `prev_hash` and `entry_hash`, because
`prev_hash` is an input to the hash and so cannot be filled in afterwards. That makes
appending a three-step operation, and getting it wrong is easy enough to be worth writing
once:

  1. read the current tail,
  2. compute the hash against it with the published RFC 8785 scheme,
  3. insert - and if another writer got there first, the database refuses and we retry.

The retry is not defensive padding. Two releases committed in the same instant would
otherwise both read the same tail and both claim it, and the database refusing one of them
is the entire reason the chain cannot silently fork.
"""

from __future__ import annotations

from typing import Any, Final

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sarana_shared.crypto.chain import GENESIS_HASH, chain_hash

_log = structlog.get_logger(__name__)

# Two writers racing is normal; twenty are not. A low ceiling turns a genuine problem -
# a stuck advisory lock, a misconfigured tail query - into a fast, loud failure rather
# than a request that hangs on retries while a dispatcher waits.
MAX_ATTEMPTS: Final = 4


class ChainAppendFailed(RuntimeError):
    """The entry could not be appended after retrying."""


async def current_tail(session: AsyncSession, *, schema: str, table: str) -> str:
    """The hash of the most recent entry, or the genesis value for an empty chain."""
    result = await session.execute(
        text(f"SELECT entry_hash FROM {schema}.{table} ORDER BY seq DESC LIMIT 1")  # noqa: S608 - schema and table are module constants, never caller input
    )
    return result.scalar_one_or_none() or GENESIS_HASH


async def append(
    session: AsyncSession,
    *,
    schema: str,
    table: str,
    columns: dict[str, Any],
    hashed_payload: dict[str, Any],
) -> dict[str, Any]:
    """Append one entry, retrying if another writer wins the race.

    `columns` is what gets inserted. `hashed_payload` is what gets hashed - deliberately
    separate, because the hash covers the entry's *meaning* and not every column the table
    happens to carry. Storage details like `id` or `created_at` differing between a
    replica and the original would otherwise make an honest record fail verification.

    Raises:
        ChainAppendFailed: after MAX_ATTEMPTS lost races.
    """
    placeholders = ", ".join(f":{name}" for name in columns)
    names = ", ".join(columns)
    statement = text(
        f"INSERT INTO {schema}.{table} ({names}, prev_hash, entry_hash) "  # noqa: S608 - column names come from the caller's own literal dict, never a request
        f"VALUES ({placeholders}, :prev_hash, :entry_hash) "
        "RETURNING seq, prev_hash, entry_hash"
    )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        previous = await current_tail(session, schema=schema, table=table)
        entry_hash = chain_hash(hashed_payload, previous)

        savepoint = await session.begin_nested()
        try:
            result = await session.execute(
                statement, {**columns, "prev_hash": previous, "entry_hash": entry_hash}
            )
        except IntegrityError as error:
            await savepoint.rollback()
            if "hash chain break" not in str(error):
                # Some other constraint - a missing entitlement, a bad enum. Retrying
                # would not help and would hide the real reason.
                raise
            _log.info(
                "chain_append_retry",
                table=f"{schema}.{table}",
                attempt=attempt,
                reason="another writer appended first",
            )
            continue

        await savepoint.commit()
        return dict(result.mappings().one())

    raise ChainAppendFailed(
        f"could not append to {schema}.{table} after {MAX_ATTEMPTS} attempts; the chain "
        "tail kept moving. Something is appending faster than this can read, or the "
        "advisory lock is not being taken."
    )
