/**
 * What an entry in the client operation log is.
 *
 * The vocabulary here is pinned to the server's. `ledger_svc.domain.sync.OperationStatus`
 * returns `applied | duplicate | conflict | blocked`, and every one of those maps onto a
 * local status below. A device that invented its own names would have to translate them
 * on every sync, and the translation is where the meaning gets lost.
 */

/** The local lifecycle of one operation. */
export const OPERATION_STATUSES = [
  /** Written on the device, not yet sent. */
  'pending',
  /** Claimed by an in-flight batch. Not re-sent while it holds this. */
  'syncing',
  /** The server has it. Eligible for purge after 30 days. */
  'synced',
  /** Held behind a gap earlier in this device's sequence. Not an error. */
  'blocked',
  /** The server refused it and a person has to look. Never merged silently. */
  'conflict',
  /** Repeated transport failure. Retried, with the reason kept. */
  'failed',
] as const;

export type OperationStatus = (typeof OPERATION_STATUSES)[number];

/** Statuses that still need something to happen before the work is safe. */
export const UNSYNCED_STATUSES: readonly OperationStatus[] = [
  'pending',
  'syncing',
  'blocked',
  'failed',
];

/** Statuses a person has to resolve. Counted separately in the status strip. */
export const ATTENTION_STATUSES: readonly OperationStatus[] = ['conflict', 'failed'];

export type OperationVerb = 'create' | 'update';

/** The entity kinds the log carries. Each has one sync route. */
export const ENTITY_TYPES = ['assessment', 'report', 'grievance'] as const;
export type EntityType = (typeof ENTITY_TYPES)[number];

export interface OperationRecord {
  readonly client_operation_id: string;
  readonly seq: number;
  readonly entity_type: EntityType;
  readonly entity_local_id: string;
  readonly op: OperationVerb;
  /** JSON. Read it with `payloadOf`, which is where the parse failure is handled. */
  readonly payload: string;
  readonly created_at: string;
  readonly synced_at: string | null;
  readonly server_id: string | null;
  readonly status: OperationStatus;
  readonly attempt_count: number;
  readonly last_error: string | null;
  readonly conflict_detail: string | null;
}

/** What a caller appends. `seq` and the timestamps are the log's to assign. */
export interface NewOperation {
  readonly entity_type: EntityType;
  readonly entity_local_id: string;
  readonly op: OperationVerb;
  readonly payload: Readonly<Record<string, unknown>>;
  /** Supplied only when replaying a retry that must keep its idempotency key. */
  readonly client_operation_id?: string;
}

export class CorruptPayloadError extends Error {
  constructor(readonly clientOperationId: string) {
    super(
      `the payload for operation ${clientOperationId} is not readable JSON. It cannot be ` +
        'sent and it cannot be repaired on the device; export the log and get it off the ' +
        'handset before anything else touches this row.',
    );
    this.name = 'CorruptPayloadError';
  }
}

export function payloadOf(record: OperationRecord): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(record.payload);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('not an object');
    }
    return parsed as Record<string, unknown>;
  } catch {
    throw new CorruptPayloadError(record.client_operation_id);
  }
}
