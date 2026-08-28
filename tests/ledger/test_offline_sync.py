"""The offline assessment sync contract.

A GN officer's phone decides on its own when to push, how often to retry, and how much of
its log to send. Nobody is watching when it goes wrong, so these tests are written as the
things a field device actually does: send the same batch twice, send it from two networks
at once, send 8-9-10 when 7 was lost, and send a log it should have discarded.

The property that matters throughout: **a gap pauses, it never skips.** Applying an update
whose create never arrived builds a household's record out of half the facts, and the
number that comes out the other end is one somebody gets paid.
"""

from __future__ import annotations

import pytest

from ledger_svc.domain.sync import (
    MAX_BATCH_OPERATIONS,
    OperationStatus,
    SyncOperation,
    SyncRefused,
    plan,
)


def op(seq: int, *, operation_id: str | None = None, kind: str = "create") -> SyncOperation:
    return SyncOperation(
        client_operation_id=operation_id or f"op-{seq:04d}",
        op=kind,
        seq=seq,
        payload={"category": "HOUSE_PARTIAL", "units": 1},
    )


def statuses(results: list) -> list[str]:
    return [result.status.value for result in results]


# --------------------------------------------------------------------------------------
# The ordinary case
# --------------------------------------------------------------------------------------


def test_a_fresh_device_applies_its_whole_log_in_order() -> None:
    planned = plan([op(3), op(1), op(2)], last_applied_seq=0, already_applied=[])

    assert [item.seq for item in planned.to_apply] == [1, 2, 3]
    assert not planned.paused


def test_a_device_continues_from_where_it_left_off() -> None:
    planned = plan([op(4), op(5)], last_applied_seq=3, already_applied=[])

    assert [item.seq for item in planned.to_apply] == [4, 5]
    assert not planned.paused


# --------------------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------------------


def test_replaying_the_whole_batch_applies_nothing_twice() -> None:
    """The case a flaky link produces on its own, several times an hour."""
    batch = [op(1), op(2), op(3)]
    already = [item.client_operation_id for item in batch]

    planned = plan(batch, last_applied_seq=3, already_applied=already)

    assert planned.to_apply == []
    assert statuses(planned.results) == ["duplicate"] * 3


def test_a_partly_applied_batch_applies_only_the_rest() -> None:
    """The truncated push: the connection died half way through the first attempt."""
    batch = [op(1), op(2), op(3), op(4)]

    planned = plan(batch, last_applied_seq=2, already_applied=["op-0001", "op-0002"])

    assert [item.seq for item in planned.to_apply] == [3, 4]
    assert statuses(planned.results) == ["duplicate", "duplicate"]


def test_a_duplicate_still_advances_the_cursor() -> None:
    """Otherwise the device replays its entire log on every sync, forever.

    The operation is on record. It is applied; it simply was not applied by this request.
    """
    planned = plan(
        [op(1), op(2), op(3)], last_applied_seq=0, already_applied=["op-0001", "op-0002"]
    )

    assert [item.seq for item in planned.to_apply] == [3]
    assert not planned.paused


# --------------------------------------------------------------------------------------
# Gaps
# --------------------------------------------------------------------------------------


def test_a_gap_pauses_the_device_and_names_the_missing_seq() -> None:
    """The rule the whole contract rests on.

    Seq 7 never arrived. Applying 8 would attach an update to a create the server has
    never seen.
    """
    planned = plan([op(8), op(9), op(10)], last_applied_seq=6, already_applied=[])

    assert planned.paused
    assert planned.missing_seq == 7
    assert planned.to_apply == []


def test_everything_after_a_gap_is_held_not_dropped() -> None:
    """Held, and reported as held. A silently dropped operation is a household whose
    damage was assessed and never recorded."""
    planned = plan([op(1), op(2), op(4), op(5)], last_applied_seq=0, already_applied=[])

    assert [item.seq for item in planned.to_apply] == [1, 2]
    assert statuses(planned.results) == ["blocked", "blocked"]
    assert planned.missing_seq == 3


def test_the_held_operations_say_what_to_do_about_it() -> None:
    """The device has to act on this without a person reading the response."""
    planned = plan([op(5)], last_applied_seq=3, already_applied=[])

    detail = planned.results[0].detail or ""
    assert "seq 4" in detail
    assert "retry" in detail


def test_a_gap_is_not_reported_as_a_conflict() -> None:
    """Different problems need different words.

    A conflict sends somebody looking for a disagreement between two records. A gap means
    one message did not arrive, and the fix is to send it.
    """
    planned = plan([op(9)], last_applied_seq=6, already_applied=[])

    assert planned.results[0].status is OperationStatus.BLOCKED
    assert planned.results[0].conflict is None


# --------------------------------------------------------------------------------------
# Conflicts, surfaced and never merged
# --------------------------------------------------------------------------------------


def test_a_new_operation_at_an_already_consumed_seq_is_a_conflict() -> None:
    """Two different operations claiming one position in an append-only log.

    ADR-006 makes assessments single-writer, so this means something is genuinely wrong -
    a device replaying a log it should have discarded, or two installations sharing an id.
    """
    planned = plan(
        [SyncOperation("op-different", "create", 2, {})],
        last_applied_seq=3,
        already_applied=[],
    )

    assert planned.results[0].status is OperationStatus.CONFLICT
    assert planned.to_apply == []


def test_a_conflict_carries_enough_to_investigate() -> None:
    planned = plan(
        [SyncOperation("op-different", "create", 2, {})],
        last_applied_seq=3,
        already_applied=[],
    )

    conflict = planned.results[0].conflict or {}
    assert conflict["seq"] == 2
    assert conflict["device_cursor"] == 3


def test_a_conflict_is_never_merged() -> None:
    """Merging would produce a damage figure neither officer wrote, on a household that
    will be paid on it."""
    planned = plan(
        [SyncOperation("op-different", "create", 2, {"cost_estimate_lkr_cents": 999})],
        last_applied_seq=3,
        already_applied=[],
    )

    assert planned.to_apply == []
    assert "merged" in (planned.results[0].detail or "")


# --------------------------------------------------------------------------------------
# Batches that cannot be ordered at all
# --------------------------------------------------------------------------------------


def test_an_empty_batch_is_refused() -> None:
    with pytest.raises(SyncRefused, match="at least one operation"):
        plan([], last_applied_seq=0, already_applied=[])


def test_two_operations_at_the_same_seq_are_refused() -> None:
    """An append-only log cannot have two entries in one position, so the batch is
    malformed rather than conflicted - nothing in it can be trusted to be in order."""
    with pytest.raises(SyncRefused, match="appears twice"):
        plan(
            [op(1), SyncOperation("op-other", "create", 1, {})],
            last_applied_seq=0,
            already_applied=[],
        )


def test_one_operation_id_at_two_sequence_numbers_is_refused() -> None:
    """The idempotency key would be ambiguous, which defeats the point of having one."""
    with pytest.raises(SyncRefused, match="idempotency key would be ambiguous"):
        plan(
            [op(1, operation_id="same"), op(2, operation_id="same")],
            last_applied_seq=0,
            already_applied=[],
        )


def test_a_seq_below_one_is_refused() -> None:
    with pytest.raises(SyncRefused, match="numbered from 1"):
        plan([op(0)], last_applied_seq=0, already_applied=[])


def test_an_implausibly_large_batch_is_refused_fast() -> None:
    """A device holding ten thousand operations has a problem this endpoint cannot fix,
    and a request that times out holding a connection helps nobody."""
    with pytest.raises(SyncRefused, match="at most"):
        plan(
            [op(index) for index in range(1, MAX_BATCH_OPERATIONS + 2)],
            last_applied_seq=0,
            already_applied=[],
        )


def test_a_batch_at_exactly_the_limit_is_accepted() -> None:
    planned = plan(
        [op(index) for index in range(1, MAX_BATCH_OPERATIONS + 1)],
        last_applied_seq=0,
        already_applied=[],
    )

    assert len(planned.to_apply) == MAX_BATCH_OPERATIONS


# --------------------------------------------------------------------------------------
# Every operation gets an answer
# --------------------------------------------------------------------------------------


def test_every_operation_is_accounted_for() -> None:
    """The device reconciles its log against this response.

    An operation that appears in neither `to_apply` nor `results` is one the device will
    consider unsent forever, or worse, consider sent.
    """
    batch = [op(1), op(2), op(3), op(5), op(6)]

    planned = plan(batch, last_applied_seq=0, already_applied=["op-0002"])

    answered = {item.client_operation_id for item in planned.to_apply}
    answered |= {result.client_operation_id for result in planned.results}

    assert answered == {item.client_operation_id for item in batch}
