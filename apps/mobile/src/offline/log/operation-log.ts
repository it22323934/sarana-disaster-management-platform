/**
 * The append-only client operation log (ADR-006).
 *
 * Every write the user makes lands here in the same transaction as the entity row it
 * describes. That pairing is the whole guarantee: a device cannot hold an assessment
 * with no operation to sync it, and cannot hold an operation pointing at a record that
 * was never written.
 *
 * The log is never truncated until the server confirms. A device wiped between sync and
 * confirmation loses data, so confirmation - not sending - is what makes a row eligible
 * for purge.
 */

import { deviceUuid7 } from '../ids.js';
import type { Clock, Database } from '../db/types.js';
import { systemClock } from '../db/types.js';
import { MAX_BATCH, planBatch, type BatchPlan } from './ordering.js';
import {
  ATTENTION_STATUSES,
  UNSYNCED_STATUSES,
  type EntityType,
  type NewOperation,
  type OperationRecord,
  type OperationStatus,
} from './types.js';

const COLUMNS =
  'client_operation_id, seq, entity_type, entity_local_id, op, payload, created_at, ' +
  'synced_at, server_id, status, attempt_count, last_error, conflict_detail';

/** What the status strip is built from. One query, because it runs on every render. */
export interface LogCounts {
  readonly pending: number;
  readonly syncing: number;
  readonly synced: number;
  readonly blocked: number;
  readonly conflict: number;
  readonly failed: number;
}

export const EMPTY_COUNTS: LogCounts = {
  pending: 0,
  syncing: 0,
  synced: 0,
  blocked: 0,
  conflict: 0,
  failed: 0,
};

export interface DeviceRow {
  readonly device_id: string;
  readonly next_seq: number;
  readonly server_cursor: number;
  readonly blocked_on_seq: number | null;
  readonly last_synced_at: string | null;
  readonly last_sync_error: string | null;
}

/** One result line from `POST /api/v1/assessments/sync`, as the server writes it. */
export interface ServerResult {
  readonly client_operation_id: string;
  readonly status: 'applied' | 'duplicate' | 'conflict' | 'blocked';
  readonly server_id?: string | null;
  readonly conflict?: Record<string, unknown> | null;
  readonly detail?: string | null;
}

export class OperationLog {
  constructor(
    private readonly db: Database,
    private readonly clock: Clock = systemClock,
  ) {}

  /**
   * Register this device, or read back the registration.
   *
   * `deviceId` is stable for the life of the installation and is what the server's sync
   * cursor is keyed by. Reinstalling produces a new one, and a new cursor, which is
   * correct: the old log went with the old installation.
   */
  async register(deviceId: string): Promise<DeviceRow> {
    await this.db.execute(
      'INSERT INTO device (id, device_id) VALUES (?, ?) ON CONFLICT (id) DO NOTHING',
      ['this', deviceId],
    );
    return this.device();
  }

  async device(): Promise<DeviceRow> {
    const [row] = await this.db.select<DeviceRow>(
      'SELECT device_id, next_seq, server_cursor, blocked_on_seq, last_synced_at, ' +
        'last_sync_error FROM device WHERE id = ?',
      ['this'],
    );
    if (!row) {
      throw new Error('the device is not registered; call register() at start-up');
    }
    return row;
  }

  /**
   * Append one operation, allocating its sequence number.
   *
   * `work` runs in the same transaction and is where the entity row is written. If it
   * throws, the operation is not appended either - the two are one write.
   */
  async append(
    operation: NewOperation,
    work?: (tx: Database) => Promise<void>,
  ): Promise<OperationRecord> {
    return this.db.transaction(async (tx) => {
      const [device] = await tx.select<{ next_seq: number }>(
        'SELECT next_seq FROM device WHERE id = ?',
        ['this'],
      );
      if (!device) throw new Error('the device is not registered; call register() at start-up');

      const seq = device.next_seq;
      const now = this.clock.now();
      const id = operation.client_operation_id ?? deviceUuid7(now);

      await tx.execute('UPDATE device SET next_seq = ? WHERE id = ?', [seq + 1, 'this']);
      await tx.execute(
        `INSERT INTO operation_log (${COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, 0, NULL, NULL)`,
        [
          id,
          seq,
          operation.entity_type,
          operation.entity_local_id,
          operation.op,
          JSON.stringify(operation.payload),
          new Date(now).toISOString(),
          'pending' satisfies OperationStatus,
        ],
      );

      if (work) await work(tx);

      const [record] = await tx.select<OperationRecord>(
        `SELECT ${COLUMNS} FROM operation_log WHERE client_operation_id = ?`,
        [id],
      );
      return record!;
    });
  }

  async all(): Promise<OperationRecord[]> {
    return this.db.select<OperationRecord>(
      `SELECT ${COLUMNS} FROM operation_log ORDER BY seq`,
    );
  }

  async byId(clientOperationId: string): Promise<OperationRecord | null> {
    const [row] = await this.db.select<OperationRecord>(
      `SELECT ${COLUMNS} FROM operation_log WHERE client_operation_id = ?`,
      [clientOperationId],
    );
    return row ?? null;
  }

  async forEntity(entityType: EntityType, localId: string): Promise<OperationRecord[]> {
    return this.db.select<OperationRecord>(
      `SELECT ${COLUMNS} FROM operation_log WHERE entity_type = ? AND entity_local_id = ? ORDER BY seq`,
      [entityType, localId],
    );
  }

  /**
   * Take the next batch and mark it in flight.
   *
   * Claiming is a transaction so two sync triggers firing together - a foreground event
   * and a connectivity change land within milliseconds of each other on a real handset -
   * cannot both carry the same operation.
   */
  async claim(limit: number = MAX_BATCH): Promise<BatchPlan> {
    return this.db.transaction(async (tx) => {
      const [device] = await tx.select<{ server_cursor: number }>(
        'SELECT server_cursor FROM device WHERE id = ?',
        ['this'],
      );
      const cursor = device?.server_cursor ?? 0;

      // Synced rows above the cursor are loaded too. They are how the planner knows a
      // position is filled rather than missing, and there are only ever a handful: a row
      // becomes synced and the cursor moves in the same run.
      const log = await tx.select<OperationRecord>(
        `SELECT ${COLUMNS} FROM operation_log WHERE status != 'synced' OR seq > ? ORDER BY seq`,
        [cursor],
      );

      const plan = planBatch(log, { serverCursor: cursor, limit });

      for (const record of plan.operations) {
        await tx.execute(
          'UPDATE operation_log SET status = ?, attempt_count = attempt_count + 1 ' +
            'WHERE client_operation_id = ?',
          ['syncing' satisfies OperationStatus, record.client_operation_id],
        );
      }

      if (plan.missingSeq !== null) {
        await tx.execute('UPDATE device SET blocked_on_seq = ? WHERE id = ?', [
          plan.missingSeq,
          'this',
        ]);
      }

      return plan;
    });
  }

  /**
   * Hand a claimed batch back after a transport failure.
   *
   * The operations return to `pending` rather than `failed` until they have been tried
   * enough times to mean something. A device in a valley fails every attempt and none of
   * those is a problem the officer can do anything about.
   */
  async release(
    clientOperationIds: readonly string[],
    { error, failAfter = 5 }: { error: string; failAfter?: number },
  ): Promise<void> {
    await this.db.transaction(async (tx) => {
      for (const id of clientOperationIds) {
        await tx.execute(
          'UPDATE operation_log SET status = CASE WHEN attempt_count >= ? THEN ? ELSE ? END, ' +
            'last_error = ? WHERE client_operation_id = ? AND status = ?',
          [
            failAfter,
            'failed' satisfies OperationStatus,
            'pending' satisfies OperationStatus,
            error,
            id,
            'syncing' satisfies OperationStatus,
          ],
        );
      }
    });
  }

  /**
   * Record what the server said about a batch.
   *
   * `duplicate` is a success, not a warning: it is the device learning about a
   * confirmation that never made it back over the network the first time.
   */
  async applyResults(results: readonly ServerResult[]): Promise<void> {
    const now = new Date(this.clock.now()).toISOString();
    await this.db.transaction(async (tx) => {
      for (const result of results) {
        switch (result.status) {
          case 'applied':
          case 'duplicate':
            await tx.execute(
              'UPDATE operation_log SET status = ?, synced_at = ?, server_id = ?, ' +
                'last_error = NULL, conflict_detail = NULL WHERE client_operation_id = ?',
              [
                'synced' satisfies OperationStatus,
                now,
                result.server_id ?? null,
                result.client_operation_id,
              ],
            );
            break;
          case 'blocked':
            await tx.execute(
              'UPDATE operation_log SET status = ?, last_error = ? WHERE client_operation_id = ?',
              [
                'blocked' satisfies OperationStatus,
                result.detail ?? null,
                result.client_operation_id,
              ],
            );
            break;
          case 'conflict':
            await tx.execute(
              'UPDATE operation_log SET status = ?, last_error = ?, conflict_detail = ? ' +
                'WHERE client_operation_id = ?',
              [
                'conflict' satisfies OperationStatus,
                result.detail ?? null,
                result.conflict ? JSON.stringify(result.conflict) : null,
                result.client_operation_id,
              ],
            );
            break;
        }
      }
    });
  }

  /** Record where the server says this device's cursor is, after a sync. */
  async recordSync({
    serverCursor,
    missingSeq,
    error = null,
  }: {
    serverCursor: number;
    missingSeq: number | null;
    error?: string | null;
  }): Promise<void> {
    await this.db.execute(
      'UPDATE device SET server_cursor = ?, blocked_on_seq = ?, last_synced_at = ?, ' +
        'last_sync_error = ? WHERE id = ?',
      [serverCursor, missingSeq, new Date(this.clock.now()).toISOString(), error, 'this'],
    );
  }

  async counts(): Promise<LogCounts> {
    const rows = await this.db.select<{ status: OperationStatus; n: number }>(
      'SELECT status, COUNT(*) AS n FROM operation_log GROUP BY status',
    );
    const counts: Record<string, number> = { ...EMPTY_COUNTS };
    for (const row of rows) counts[row.status] = row.n;
    return counts as unknown as LogCounts;
  }

  /** How much work is on this device that the server has not confirmed. */
  async unsyncedCount(): Promise<number> {
    const placeholders = UNSYNCED_STATUSES.map(() => '?').join(', ');
    const [row] = await this.db.select<{ n: number }>(
      `SELECT COUNT(*) AS n FROM operation_log WHERE status IN (${placeholders})`,
      [...UNSYNCED_STATUSES],
    );
    return row?.n ?? 0;
  }

  /** How many rows a person has to resolve before this device can make progress. */
  async attentionCount(): Promise<number> {
    const placeholders = ATTENTION_STATUSES.map(() => '?').join(', ');
    const [row] = await this.db.select<{ n: number }>(
      `SELECT COUNT(*) AS n FROM operation_log WHERE status IN (${placeholders})`,
      [...ATTENTION_STATUSES],
    );
    return row?.n ?? 0;
  }

  /**
   * Drop confirmed operations older than the retention window.
   *
   * Only `synced` rows, and only by `synced_at` - a row whose confirmation arrived
   * yesterday stays for thirty days from yesterday, however old the write was. A device
   * that spent a month offline does not lose its log the moment it reconnects.
   */
  async purgeSynced(retentionDays = 30): Promise<number> {
    const cutoff = new Date(this.clock.now() - retentionDays * 86_400_000).toISOString();
    const [before] = await this.db.select<{ n: number }>(
      "SELECT COUNT(*) AS n FROM operation_log WHERE status = 'synced' AND synced_at < ?",
      [cutoff],
    );
    await this.db.execute(
      "DELETE FROM operation_log WHERE status = 'synced' AND synced_at < ?",
      [cutoff],
    );
    return before?.n ?? 0;
  }
}
