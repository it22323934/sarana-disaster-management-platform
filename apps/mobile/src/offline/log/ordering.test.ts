/**
 * What may go in the next batch.
 *
 * This is the client half of the sync contract, and the rules it enforces are the ones
 * that decide whether a household's damage record is rebuilt correctly or out of order.
 * Every case here corresponds to a case in `ledger_svc.domain.sync.plan`; where the two
 * disagree the server is right and this file is the bug.
 */

import { describe, expect, it } from 'vitest';

import { MAX_BATCH, planBatch, unsyncedSeqs } from './ordering.js';
import type { OperationRecord, OperationStatus } from './types.js';

function op(seq: number, status: OperationStatus = 'pending'): OperationRecord {
  return {
    client_operation_id: `op-${seq}`,
    seq,
    entity_type: 'assessment',
    entity_local_id: `asm-${seq}`,
    op: 'create',
    payload: '{}',
    created_at: '2026-09-08T06:00:00.000Z',
    synced_at: status === 'synced' ? '2026-09-08T06:01:00.000Z' : null,
    server_id: null,
    status,
    attempt_count: 0,
    last_error: null,
    conflict_detail: null,
  };
}

describe('planBatch', () => {
  it('sends nothing when the log is empty', () => {
    const plan = planBatch([], { serverCursor: 0 });
    expect(plan.operations).toEqual([]);
    expect(plan.missingSeq).toBeNull();
    expect(plan.blockedBy).toBeNull();
  });

  it('sends a contiguous run in seq order', () => {
    const plan = planBatch([op(3), op(1), op(2)], { serverCursor: 0 });
    expect(plan.operations.map((record) => record.seq)).toEqual([1, 2, 3]);
  });

  it('starts from the server cursor, not from one', () => {
    // The server has 1-4 already. Resending them costs a round trip on a link that may
    // only be open for seconds.
    const plan = planBatch([op(5), op(6)], { serverCursor: 4 });
    expect(plan.operations.map((record) => record.seq)).toEqual([5, 6]);
  });

  it('resends an operation below the cursor that the device never saw confirmed', () => {
    // The response was lost, not the write. The server reports it as a duplicate, which
    // is how the device learns the confirmation it missed.
    const plan = planBatch([op(3), op(4)], { serverCursor: 5 });
    expect(plan.operations.map((record) => record.seq)).toEqual([3, 4]);
  });

  it('stops at a gap and reports the missing seq rather than applying out of order', () => {
    // Applying 9 without 8 would rebuild a record from an update whose create never
    // arrived. The device is told which seq is missing and holds everything after it.
    const plan = planBatch([op(7), op(9), op(10)], { serverCursor: 6 });
    expect(plan.operations.map((record) => record.seq)).toEqual([7]);
    expect(plan.missingSeq).toBe(8);
  });

  it('reports a gap at the very start of the run', () => {
    const plan = planBatch([op(4)], { serverCursor: 1 });
    expect(plan.operations).toEqual([]);
    expect(plan.missingSeq).toBe(2);
  });

  it('stops at a conflict and names the operation that is jamming the queue', () => {
    // A conflict is never merged and never retried on its own, so everything behind it
    // waits for a person. The status strip counts exactly this.
    const plan = planBatch([op(1), op(2, 'conflict'), op(3)], { serverCursor: 0 });
    expect(plan.operations.map((record) => record.seq)).toEqual([1]);
    expect(plan.blockedBy?.seq).toBe(2);
    expect(plan.missingSeq).toBeNull();
  });

  it('does not re-send an operation another batch is already carrying', () => {
    const plan = planBatch([op(1, 'syncing'), op(2)], { serverCursor: 0 });
    expect(plan.operations).toEqual([]);
  });

  it('retries a blocked operation, because the gap in front of it may now be filled', () => {
    const plan = planBatch([op(1, 'blocked'), op(2, 'blocked')], { serverCursor: 0 });
    expect(plan.operations.map((record) => record.seq)).toEqual([1, 2]);
  });

  it('retries a failed operation', () => {
    const plan = planBatch([op(1, 'failed')], { serverCursor: 0 });
    expect(plan.operations.map((record) => record.seq)).toEqual([1]);
  });

  it('ignores synced operations entirely', () => {
    const plan = planBatch([op(1, 'synced'), op(2, 'synced'), op(3)], { serverCursor: 2 });
    expect(plan.operations.map((record) => record.seq)).toEqual([3]);
  });

  it('never sends more than the batch limit', () => {
    const log = Array.from({ length: 200 }, (_, index) => op(index + 1));
    expect(planBatch(log, { serverCursor: 0 }).operations).toHaveLength(MAX_BATCH);
    expect(planBatch(log, { serverCursor: 0, limit: 7 }).operations).toHaveLength(7);
  });

  it('caps at the limit before it reaches a later gap', () => {
    // The batch is full, so the gap is not this batch's problem yet. Reporting it here
    // would tell the officer their log is broken when the next batch will fill it.
    const log = [...Array.from({ length: 10 }, (_, index) => op(index + 1)), op(50)];
    const plan = planBatch(log, { serverCursor: 0, limit: 5 });
    expect(plan.operations).toHaveLength(5);
    expect(plan.missingSeq).toBeNull();
  });
});

describe('unsyncedSeqs', () => {
  it('lists every seq the server has not confirmed, in order', () => {
    const log = [op(1, 'synced'), op(3), op(2, 'conflict'), op(4, 'blocked')];
    expect(unsyncedSeqs(log)).toEqual([2, 3, 4]);
  });
});
