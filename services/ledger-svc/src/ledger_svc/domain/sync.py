"""The offline assessment sync contract.

A GN officer assesses damage in a division with no signal, on a phone, possibly for two
days. The Field Companion writes to an append-only local operation log (ADR-006) and
pushes the whole log when it next sees a network. That push is expected to be retried,
truncated mid-flight, and sent twice from two different networks.

So three rules shape everything here:

**Replay is safe and expected.** `client_operation_id` is the idempotency key. Sending the
same fifty operations five times concurrently must leave exactly fifty assessments.

**A gap pauses the device, it does not skip.** If seq 7 never arrived, applying 8 and 9
would build a household's record out of an update whose create is missing. The device is
told which seq is missing and stops there; everything after it is reported `blocked`, not
silently dropped and not applied out of order.

**Conflicts are surfaced, never merged.** ADR-006 makes assessments single-writer, so a
conflict means something is genuinely wrong - two devices claiming one household, or a
device replaying a log it should have discarded. Merging would produce a damage figure
neither officer wrote, attached to a household that will be paid on it.

Nothing here touches the database. `plan()` is pure so the ordering rules above can be
tested exhaustively without a Postgres container, which is the only way the gap logic gets
the attention it needs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

# A field device that has been offline for two days holds a lot; one that sends ten
# thousand operations in a batch is not a field device. The cap makes an implausible batch
# a fast, clear refusal rather than a request that times out holding a connection.
MAX_BATCH_OPERATIONS: Final = 500


class SyncRefused(ValueError):
    """The batch itself is malformed, before any operation is considered."""


class OperationStatus(StrEnum):
    """What happened to one operation in a batch."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    # Not in the brief's list, and deliberately added. The brief says a gap "pauses that
    # device's sync and reports which seq is missing" - which needs a status of its own,
    # because reporting a held operation as a conflict would send the officer looking for
    # a disagreement that does not exist.
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class SyncOperation:
    """One entry from a device's local operation log."""

    client_operation_id: str
    op: str
    seq: int
    payload: dict[str, Any]
    target: str | None = None


@dataclass(frozen=True, slots=True)
class SyncResult:
    """What the server did with one operation, and enough for the device to move on."""

    client_operation_id: str
    status: OperationStatus
    server_id: UUID | None = None
    conflict: dict[str, Any] | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "client_operation_id": self.client_operation_id,
            "status": self.status.value,
        }
        if self.server_id is not None:
            body["server_id"] = str(self.server_id)
        if self.conflict is not None:
            body["conflict"] = self.conflict
        if self.detail is not None:
            body["detail"] = self.detail
        return body


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """What to apply, what to report back, and where the device's cursor lands."""

    to_apply: list[SyncOperation] = field(default_factory=list)
    results: list[SyncResult] = field(default_factory=list)
    missing_seq: int | None = None

    @property
    def paused(self) -> bool:
        """True when a gap stopped this batch part-way through."""
        return self.missing_seq is not None


def assert_batch_is_wellformed(operations: Sequence[SyncOperation]) -> None:
    """Refuse a batch that cannot be ordered, before touching anything.

    Raises:
        SyncRefused: for an oversized batch, a repeated seq, or a repeated operation id.
    """
    if not operations:
        raise SyncRefused("a sync batch must contain at least one operation")

    if len(operations) > MAX_BATCH_OPERATIONS:
        raise SyncRefused(
            f"a sync batch may carry at most {MAX_BATCH_OPERATIONS} operations; this one "
            f"carries {len(operations)}. Split it - a device holding more than this has a "
            "problem the sync endpoint cannot fix."
        )

    by_seq: dict[int, str] = {}
    for operation in operations:
        if operation.seq < 1:
            raise SyncRefused(
                f"operation {operation.client_operation_id} has seq {operation.seq}; a "
                "device operation log is numbered from 1"
            )
        existing = by_seq.get(operation.seq)
        if existing is not None and existing != operation.client_operation_id:
            raise SyncRefused(
                f"seq {operation.seq} appears twice in this batch, as "
                f"{existing} and {operation.client_operation_id}. The device log is "
                "append-only, so two operations cannot hold one position."
            )
        by_seq[operation.seq] = operation.client_operation_id

    ids = [operation.client_operation_id for operation in operations]
    if len(set(ids)) != len(ids):
        raise SyncRefused(
            "the same client_operation_id appears twice in this batch with different "
            "sequence numbers; the idempotency key would be ambiguous"
        )


def _blocked(operation: SyncOperation, missing: int) -> SyncResult:
    return SyncResult(
        operation.client_operation_id,
        OperationStatus.BLOCKED,
        detail=(
            f"held: this device has not sent seq {missing}. Send it, then retry this "
            "batch - operations are applied in order."
        ),
    )


def plan(
    operations: Sequence[SyncOperation],
    *,
    last_applied_seq: int,
    already_applied: Iterable[str],
) -> SyncPlan:
    """Decide what to apply, in order, stopping at the first gap.

    `last_applied_seq` is this device's cursor - the highest seq the server has accepted
    from it. `already_applied` is the set of `client_operation_id`s already stored, which
    is what makes a full replay cheap: they come back as `duplicate` and the cursor does
    not move backwards.

    Raises:
        SyncRefused: if the batch cannot be ordered at all.
    """
    assert_batch_is_wellformed(operations)

    seen = set(already_applied)
    ordered = sorted(operations, key=lambda operation: operation.seq)

    to_apply: list[SyncOperation] = []
    results: list[SyncResult] = []
    missing: int | None = None
    expected = last_applied_seq + 1

    for operation in ordered:
        if missing is not None:
            # The gap has already stopped this device. Everything after it waits, so the
            # record is rebuilt in the order the officer actually wrote it.
            results.append(_blocked(operation, missing))
            continue

        if operation.client_operation_id in seen:
            # A replay of something already stored. The device is told so, and the cursor
            # still advances past it - it *is* applied, just not by this request.
            results.append(SyncResult(operation.client_operation_id, OperationStatus.DUPLICATE))
            expected = max(expected, operation.seq + 1)
            continue

        if operation.seq < expected:
            # Behind the cursor but not on record: the server accepted this position from
            # a different operation. Reported, never merged.
            results.append(
                SyncResult(
                    operation.client_operation_id,
                    OperationStatus.CONFLICT,
                    conflict={
                        "reason": "seq_already_consumed",
                        "seq": operation.seq,
                        "device_cursor": expected - 1,
                    },
                    detail=(
                        f"seq {operation.seq} was already applied from a different "
                        "operation on this device. Nothing has been merged; this needs a "
                        "person to look at the device log."
                    ),
                )
            )
            continue

        if operation.seq > expected:
            missing = expected
            results.append(_blocked(operation, missing))
            continue

        to_apply.append(operation)
        expected += 1

    return SyncPlan(to_apply=to_apply, results=results, missing_seq=missing)
