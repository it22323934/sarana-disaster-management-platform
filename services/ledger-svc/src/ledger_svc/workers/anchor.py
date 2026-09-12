"""The daily anchor job (ADR-005).

A hash chain inside a database you control proves nothing, because the operator can
recompute the whole chain after tampering. This job is what closes that hole: at 00:00
Colombo it builds a Merkle root over the day's disbursements and writes it to S3 Object
Lock in **compliance mode**, where it cannot be altered or deleted by anyone - including
the account root user - for the retention period.

That single object is the difference between "auditable" and "auditable by us".

Two behaviours here are deliberate and easy to get wrong:

**It anchors every unanchored day, not yesterday.** If the job did not run for three days,
the next run writes three anchors. A missing anchor is a hole in the public proof and it
never fills itself.

**A failed anchor is loud.** It logs at error and raises, so the alarm fires. An anchor job
that swallows its own failure leaves the chain unanchored while the dashboard keeps saying
it is verified, which is worse than not having one.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger_svc.adapters.events import publish
from ledger_svc.repo import queries
from sarana_shared.crypto.merkle import Anchor, build_anchor
from sarana_shared.domain.ids import uuid7
from sarana_shared.domain.time import utc_now

_log = structlog.get_logger(__name__)

COLOMBO = ZoneInfo("Asia/Colombo")

# Seven years. Long enough to outlast the recovery programme, the parliament that
# authorised it, and most of the officials involved.
RETENTION_YEARS = 7

ANCHOR_EVENT = "sarana.aid.ledger.anchored"


class AnchorStore(Protocol):
    """Somewhere an anchor can be written and never changed.

    A Protocol rather than a boto3 call so the job is testable without AWS, and so the
    local stack can run the whole loop against MinIO or a directory. The interface is what
    matters: `put` must be write-once.
    """

    async def put(self, *, key: str, body: dict[str, Any], retain_until: datetime) -> str:
        """Store the anchor immutably and return its URI."""
        ...


class NullAnchorStore:
    """Records anchors in the database only, and says so.

    Used when no object store is configured - a local stack, or a test. It returns None
    for the URI rather than a plausible-looking `s3://` string, because an anchor that
    claims to be in Object Lock and is not would make the verification story a lie at
    exactly the point somebody relies on it.
    """

    async def put(self, *, key: str, body: dict[str, Any], retain_until: datetime) -> str | None:
        _log.warning(
            "anchor_not_externally_stored",
            key=key,
            reason="no object store configured; the anchor exists only in the database",
        )
        return None


async def anchor_day(
    session: AsyncSession, anchor_date: date, *, store: AnchorStore | NullAnchorStore
) -> dict[str, Any] | None:
    """Build and store the Merkle root for one Colombo day.

    Returns None for a day with no disbursements. An empty anchor would assert that
    nothing happened, which is a claim rather than a proof - and `entry_count > 0` on the
    table refuses it anyway.
    """
    entries = await queries.entries_for_day(session, anchor_date)
    if not entries:
        return None

    if any(row["entry_hash"] is None for row in entries):
        # Cannot happen through `chain_writer`, which supplies both hashes, and the
        # trigger refuses a row without them. If it ever does, anchoring around the gap
        # would produce a root that verifies while covering an entry nobody can check.
        raise RuntimeError(
            f"{anchor_date} has disbursements with no entry_hash. Refusing to anchor: a "
            "root computed over a gap verifies while proving nothing about the gap."
        )

    # The rows go in whole. `leaf_hash` strips the four non-payload fields itself, so the
    # leaves are the same bytes a verifier recomputes from the public feed, while
    # `build_anchor` still sees the `seq` it needs to record the range it covers.
    # The previous day's *anchor hash*, not its merkle root. The root commits to that
    # day's entries; the anchor hash commits to the whole record including its own
    # predecessor, which is what makes a removed day detectable.
    previous_row = await queries.latest_anchor(session)
    previous_hash = (
        Anchor(
            date=str(previous_row["date"]),
            merkle_root=str(previous_row["merkle_root"]),
            entry_count=int(previous_row["entry_count"]),
            first_seq=int(previous_row["first_seq"]),
            last_seq=int(previous_row["last_seq"]),
            prev_anchor_hash=previous_row["prev_anchor_hash"],
        ).anchor_hash()
        if previous_row
        else None
    )

    anchor = build_anchor(
        [dict(row) for row in entries],
        date=str(anchor_date),
        prev_anchor_hash=previous_hash,
    )

    retain_until = utc_now().replace(microsecond=0) + timedelta(days=365 * RETENTION_YEARS)
    key = f"anchors/{anchor_date:%Y/%m/%d}.json"
    uri = await store.put(key=key, body=anchor.as_dict(), retain_until=retain_until)

    stored = await queries.insert_anchor(
        session,
        id=uuid7(),
        anchor_date=anchor_date,
        merkle_root=anchor.merkle_root,
        prev_anchor_hash=anchor.prev_anchor_hash,
        entry_count=anchor.entry_count,
        first_seq=anchor.first_seq,
        last_seq=anchor.last_seq,
        s3_object_lock_uri=uri,
        published_at=utc_now(),
    )
    if stored is None:
        # Another run got there first. Not an error: the anchor exists, which is the point.
        _log.info("anchor_already_present", anchor_date=str(anchor_date))
        return None

    publish(
        session,
        ANCHOR_EVENT,
        {
            "anchor_date": str(anchor_date),
            "merkle_root": anchor.merkle_root,
            "prev_anchor_hash": anchor.prev_anchor_hash,
            "entry_count": anchor.entry_count,
            "first_seq": anchor.first_seq,
            "last_seq": anchor.last_seq,
            "object_lock_uri": uri,
            "externally_anchored": uri is not None,
        },
        subject=str(anchor_date),
    )
    _log.info(
        "ledger_anchored",
        anchor_date=str(anchor_date),
        merkle_root=anchor.merkle_root,
        entry_count=anchor.entry_count,
        externally_anchored=uri is not None,
    )
    return stored


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    store: AnchorStore | NullAnchorStore | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Anchor every completed day that does not have one yet.

    Raises:
        RuntimeError: if a day cannot be anchored. Page-worthy on purpose - the public
            proof is incomplete until somebody looks.
    """
    resolved_store = store or NullAnchorStore()
    when = today or utc_now().astimezone(COLOMBO).date()
    written: list[dict[str, Any]] = []

    async with session_factory() as session:
        days = await queries.unanchored_days(session, when)

        if len(days) > 1:
            _log.warning(
                "anchor_backlog",
                days=len(days),
                oldest=str(days[0]),
                reason="the anchor job did not run, or ran and failed, on these days",
            )

        for day in days:
            result = await anchor_day(session, day, store=resolved_store)
            if result is not None:
                written.append(result)

        await session.commit()

    return written


def seconds_until_next_midnight(now: datetime | None = None) -> float:
    """How long until 00:00 Colombo.

    Colombo rather than UTC because the anchor covers a Colombo day, and a boundary that
    drifted against the day it describes would put some releases in the wrong anchor.
    """
    moment = (now or utc_now()).astimezone(COLOMBO)
    tomorrow = (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max((tomorrow - moment).total_seconds(), 1.0)


class AnchorWorker:
    """Runs `run_once` at every Colombo midnight.

    Sleeps to the next boundary rather than on a fixed interval, so a restart at 23:58
    does not skip the day. Catches and logs its own failures so the loop survives, but
    logs them at error - the alarm is on the log line, not on the process dying.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        store: AnchorStore | NullAnchorStore | None = None,
    ) -> None:
        self._factory = session_factory
        self._store = store or NullAnchorStore()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="ledger-anchor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        # Catch up on start. A process that has been down over a midnight has a hole in
        # the public proof, and waiting until the next boundary would leave it there.
        await self._tick()

        while True:
            await asyncio.sleep(seconds_until_next_midnight())
            await self._tick()

    async def _tick(self) -> None:
        try:
            written = await run_once(self._factory, store=self._store)
        except Exception:  # noqa: BLE001 - the loop must survive; the alarm is the log line
            _log.exception(
                "anchor_job_failed",
                impact=(
                    "the ledger is unanchored for at least one day; the public "
                    "verification story is incomplete until this is resolved"
                ),
            )
            return

        if written:
            _log.info("anchor_run_complete", anchors_written=len(written))
