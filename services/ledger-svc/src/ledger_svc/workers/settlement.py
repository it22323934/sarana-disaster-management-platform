"""The settlement poller: finding out that a released payment never arrived.

The rail accepts a transfer immediately and settles it later. Between those two moments the
ledger has recorded a release, hashed it and published it — and about three transfers in a
hundred never settle at all. Nothing else in the platform would ever find out.

This job closes that. It asks the rail about every payment whose outcome is still unknown,
and when one has failed it writes the compensating entry, raises the household's grievance
and reopens the entitlement, in one transaction.

Three behaviours are deliberate:

**It polls; it does not wait for a webhook.** The rail's callback is registered and it is
an optimisation, never the only path. A webhook that silently stops arriving looks exactly
like a quiet day — and a quiet day and a broken integration must not be indistinguishable
when the difference is households not being paid.

**A rail that is down is not a failed payment.** `GovUpstreamError` leaves the disbursement
exactly as it was, to be asked about again next pass. Treating an unreachable bank as a
returned payment would reverse money that is on its way, raise grievances nobody needs, and
do it to every household at once.

**It never retries the transfer.** Re-sending to an account that just rejected it produces
a second failure and a ledger claiming two payments. Paying again is a new release through
the human gate, after a person has looked at why the first one bounced.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger_svc.adapters.events import publish
from ledger_svc.domain import grievance as grievance_domain
from ledger_svc.domain import reversal as domain
from ledger_svc.repo import chain_writer, queries
from sarana_shared.adapters.gov.base import GovRecordNotFound, GovUpstreamError
from sarana_shared.adapters.gov.payment import PaymentClient, TransferState
from sarana_shared.domain.ids import uuid7
from sarana_shared.events import catalogue

_log = structlog.get_logger(__name__)

# How often to ask. Long enough that a national disbursement run does not hammer the rail,
# short enough that a household is not left uninformed for a working day.
POLL_INTERVAL_SECONDS: Final = 900.0

# How far back to look. A payment nobody has resolved in a month is a case for a person,
# not something more polling will fix, and an unbounded work list means the poller spends
# its time on the oldest failures rather than the newest.
WINDOW_DAYS: Final = 30

# Rail states that mean the money came back.
FAILED_STATES: Final[frozenset[TransferState]] = frozenset(
    {TransferState.FAILED, TransferState.RETURNED}
)

# What to record when the rail says a transfer failed but gives no reason. Not silence: a
# reversal with no reason still has to tell the household something, and RAIL_RETURNED at
# least says truthfully that the bank sent it back and somebody is looking into it.
DEFAULT_REASON: Final = domain.ReversalReason.RAIL_RETURNED


@dataclass(frozen=True, slots=True)
class PollResult:
    """What one pass did. Returned so a test can assert on it without reading logs."""

    checked: int = 0
    reversed_count: int = 0
    settled: int = 0
    unreachable: int = 0

    @property
    def acted(self) -> bool:
        return bool(self.reversed_count)


async def record_reversal(
    session: AsyncSession,
    *,
    disbursement_id: UUID,
    reason: str,
    rail_reference: str | None,
    correlation_id: str,
) -> dict[str, Any] | None:
    """Write a compensating entry and everything that must accompany it.

    All four or none. A reversal that landed without its grievance would take the money
    back off the books and leave the household uninformed, which is worse than the failed
    payment it was correcting — so this is one transaction and the caller commits it.

    Returns None if the payment is already reversed, which is the normal case on the second
    pass over the same failure.
    """
    context = await queries.reversal_context_row(session, disbursement_id)
    if context is None or context["reversed_at"] is not None:
        return None

    entry = domain.reverse(
        disbursement_id=disbursement_id,
        entitlement_id=UUID(context["entitlement_id"]),
        amount_lkr_cents=int(context["amount_lkr_cents"]),
        reason=reason,
        rail_reference=rail_reference or context["payment_ref"],
        correlation_id=correlation_id,
        # This is a worker. `MACHINE_REPORTABLE` refuses the reasons that are judgements
        # about what somebody did rather than observations of what a bank returned.
        by_machine=True,
    )

    # The household's case is opened first. `aid.disbursement_reversal` is append-only, so
    # the entry has to be complete when it lands - a case number could never be attached
    # afterwards, and a reversal without one is a household nobody told.
    new_grievance = grievance_domain.from_failed_transfer(
        household_id=UUID(context["household_id"]),
        disbursement_id=disbursement_id,
        description=entry.grievance_description(),
        assigned_ds_division_code=context["gn_division_code"],
        correlation_id=correlation_id,
    )
    grievance_id = uuid7()
    grievance = await queries.insert_grievance(
        session, **new_grievance.as_columns(grievance_id=grievance_id)
    )

    stored = await chain_writer.append(
        session,
        schema="aid",
        table="disbursement_reversal",
        columns=entry.as_columns(grievance_id=grievance_id),
        hashed_payload=entry.hashed_payload(),
    )

    # APPROVED, not REJECTED. The approvals still stand — what failed was the transfer,
    # not the decision — so the household can be paid the moment somebody has better bank
    # details. Leaving it DISBURSED would bar them permanently.
    await queries.set_entitlement_status(session, UUID(context["entitlement_id"]), "APPROVED")

    publish(
        session,
        catalogue.AID_DISBURSEMENT_REVERSED,
        {
            "reversal_id": str(entry.id),
            "disbursement_id": str(disbursement_id),
            "entitlement_id": context["entitlement_id"],
            # The consumer needs this to know who to message. Sent by both writers of this
            # event - the poller and the endpoint - because one event with two shapes is a
            # consumer that works until the other path fires.
            "household_id": context["household_id"],
            "amount_lkr_cents": entry.amount_lkr_cents,
            "reason": entry.reason.value,
            "needs_new_bank_details": entry.reason.needs_new_bank_details,
            "grievance_id": str(grievance_id),
            "grievance_ref": grievance["public_ref"],
            "seq": stored["seq"],
            "entry_hash": stored["entry_hash"],
            "simulated": True,
        },
        subject=str(disbursement_id),
    )
    _log.info(
        "settlement_reversed",
        disbursement_id=str(disbursement_id),
        reason=entry.reason.value,
        amount_lkr_cents=entry.amount_lkr_cents,
        grievance_ref=grievance["public_ref"],
        seq=stored["seq"],
    )
    return {**stored, "reversal_id": str(entry.id), "grievance_ref": grievance["public_ref"]}


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    rail: PaymentClient,
    window_days: int = WINDOW_DAYS,
    limit: int = 200,
) -> PollResult:
    """Ask the rail about every payment whose outcome is still unknown.

    Never raises for one payment. A rail that cannot answer about one transfer must not
    stop the pass, because the next transfer in the list may be the one that failed.
    """
    checked = reversed_count = settled = unreachable = 0

    async with session_factory() as session:
        pending = await queries.pending_settlement(session, window_days=window_days, limit=limit)

        for row in pending:
            checked += 1
            reference = row["payment_ref"]
            try:
                transfer = await rail.transfer(reference)
            except GovRecordNotFound:
                # The rail has never heard of a reference the ledger says it sent. That is
                # a reconciliation problem for a person, not a failed payment: reversing on
                # it would take money back off the books on the strength of an absence.
                _log.error(
                    "settlement_reference_unknown_to_rail",
                    disbursement_id=row["disbursement_id"],
                    payment_ref=reference,
                    impact="the ledger and the rail disagree about a payment that was sent",
                )
                continue
            except GovUpstreamError:
                # The bank is unreachable. Not a failure of this payment; ask again later.
                unreachable += 1
                continue

            if transfer.state in FAILED_STATES:
                # `FailureReason` and `ReversalReason` share their member names by design,
                # and `tests/ledger/test_vocabularies.py` asserts the rail cannot report
                # one the schema will not store. Both are StrEnum, so `.value` is the
                # string either way.
                reason = (transfer.failure_reason or DEFAULT_REASON).value
                written = await record_reversal(
                    session,
                    disbursement_id=UUID(row["disbursement_id"]),
                    reason=reason,
                    rail_reference=reference,
                    correlation_id=str(uuid7()),
                )
                if written is not None:
                    reversed_count += 1
            elif transfer.money_moved:
                settled += 1

        await session.commit()

    if unreachable:
        _log.warning(
            "settlement_rail_unreachable",
            unreachable=unreachable,
            checked=checked,
            impact="these payments will be asked about again next pass",
        )

    return PollResult(
        checked=checked,
        reversed_count=reversed_count,
        settled=settled,
        unreachable=unreachable,
    )


class SettlementWorker:
    """Runs `run_once` on a fixed interval.

    Catches and logs its own failures so the loop survives a bad pass, but logs them at
    error: the alarm is the log line, not the process dying. A settlement poller that quits
    silently leaves failed payments looking successful indefinitely, which is the exact
    condition it exists to detect.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        rail: PaymentClient,
        interval_seconds: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._factory = session_factory
        self._rail = rail
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="ledger-settlement")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            # Sleep first. A process restarting in a crash loop would otherwise poll the
            # rail on every start, and the rail is somebody else's system.
            await asyncio.sleep(self._interval)
            await self._tick()

    async def _tick(self) -> None:
        try:
            result = await run_once(self._factory, rail=self._rail)
        except Exception:  # noqa: BLE001 - the loop must survive; the alarm is the log line
            _log.exception(
                "settlement_poll_failed",
                impact=(
                    "payments that failed on the rail are still recorded as released, and "
                    "the households concerned have not been told"
                ),
            )
            return

        if result.acted:
            _log.info(
                "settlement_poll_complete",
                checked=result.checked,
                reversed=result.reversed_count,
                settled=result.settled,
            )
