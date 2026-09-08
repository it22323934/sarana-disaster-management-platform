/**
 * What may go in the next batch, decided before anything touches the network.
 *
 * This is the client half of `ledger_svc.domain.sync.plan`. The server refuses to apply
 * operations out of sequence and holds everything after a gap; the device does the same
 * check first, so a hole in the local log is reported as a hole rather than discovered
 * as forty `blocked` results after a round trip on a 2G link.
 *
 * Pure on purpose. The ordering rules are the part that loses a household's assessment
 * if they are wrong, and they get tested exhaustively here rather than through an
 * emulator.
 */

import type { OperationRecord, OperationStatus } from './types.js';

/** The server takes at most 500; the device sends 50, so a batch fits one 2G window. */
export const MAX_BATCH = 50;

/** Statuses that may be sent. `syncing` is excluded: another batch already holds it. */
const SENDABLE: readonly OperationStatus[] = ['pending', 'blocked', 'failed'];

export interface BatchPlan {
  /** Contiguous, in seq order, ready to send. May be empty. */
  readonly operations: readonly OperationRecord[];
  /**
   * The seq the device cannot get past, if any.
   *
   * Set when the log itself has a hole - an operation that was written and is no longer
   * on the device. Nothing after it may be sent, because the server would rebuild the
   * record out of an update whose create is missing.
   */
  readonly missingSeq: number | null;
  /**
   * The operation that is jamming the queue, if one is.
   *
   * A conflict is never merged and never retried on its own, so everything behind it
   * waits for a person. This is what the status strip counts as needing attention.
   */
  readonly blockedBy: OperationRecord | null;
}

/**
 * Choose the next batch.
 *
 * `log` must include synced operations above the cursor as well as unsent ones. The
 * planner walks the sequence, and a synced row is how it knows a position is filled -
 * dropping them would make every confirmed operation look like a hole.
 *
 * `serverCursor` is the highest seq the server has confirmed for this device.
 */
export function planBatch(
  log: readonly OperationRecord[],
  { serverCursor, limit = MAX_BATCH }: { serverCursor: number; limit?: number },
): BatchPlan {
  const sorted = [...log].sort((a, b) => a.seq - b.seq);
  const operations: OperationRecord[] = [];
  const expectedStart = serverCursor + 1;

  // Unsent operations the server has already moved past.
  //
  // The device only reaches this state one way: the results were written locally and the
  // process died before the cursor was, or a support export was restored. Resending is
  // how it gets resolved - the server answers `duplicate` for one it has, `conflict` for
  // one it does not, and either answer unsticks the row. They go first because they are
  // behind everything else in sequence.
  for (const record of sorted) {
    if (record.seq >= expectedStart) break;
    if (record.status === 'synced') continue;
    if (record.status === 'conflict') {
      return { operations, missingSeq: null, blockedBy: record };
    }
    if (!SENDABLE.includes(record.status)) continue;
    operations.push(record);
    if (operations.length >= limit) {
      return { operations, missingSeq: null, blockedBy: null };
    }
  }

  let expected = expectedStart;

  for (const record of sorted) {
    if (record.seq < expected) continue;

    if (record.seq > expected) {
      // A hole. Not "skip it" - the operations after it describe a record whose earlier
      // half never reached the server.
      return { operations, missingSeq: expected, blockedBy: null };
    }

    if (record.status === 'synced') {
      // Confirmed but the cursor has not caught up. The position is filled; move on.
      expected += 1;
      continue;
    }

    if (record.status === 'conflict') {
      return { operations, missingSeq: null, blockedBy: record };
    }

    if (!SENDABLE.includes(record.status)) {
      // `syncing`: another batch is already carrying it. Stop rather than send it twice -
      // the server would treat the second copy as a duplicate, but the device would then
      // have two batches racing to write one row's result.
      return { operations, missingSeq: null, blockedBy: null };
    }

    operations.push(record);
    expected += 1;

    if (operations.length >= limit) break;
  }

  return { operations, missingSeq: null, blockedBy: null };
}

/**
 * Every seq the device holds that the server has not confirmed.
 *
 * Used by the export path: a device that has to be wiped with unsynced work on it hands
 * the officer a file, and the file has to say which operations it contains.
 */
export function unsyncedSeqs(log: readonly OperationRecord[]): number[] {
  return log
    .filter((record) => record.status !== 'synced')
    .map((record) => record.seq)
    .sort((a, b) => a - b);
}
