/**
 * The sync engine.
 *
 * Reconciliation, never a blocking step. Nothing in the UI waits on this class: a write
 * lands in SQLite and is immediately visible, and the engine catches up whenever it can.
 * Its whole job is to be safe to interrupt.
 *
 * Triggers (file 22): app foreground, connectivity regained, a background task every
 * fifteen minutes, pull-to-refresh, and immediately after any write when online. All five
 * arrive here as `request(reason)`, and all five are deduplicated - two of them landing
 * within milliseconds of each other on a real handset is the normal case, not an edge one.
 *
 * The invariants, each of which has a test named after it:
 *
 *   - One run at a time. A second `request` while a run is in flight is remembered and
 *     runs after it, rather than racing it.
 *   - Operations leave in `seq` order and a gap stops the device rather than skipping.
 *   - A batch that fails in transit returns to the queue whole. Nothing is half-applied,
 *     because `client_operation_id` makes a resend a duplicate rather than a second row.
 *   - Text before media, always.
 */

import type { Clock } from '../db/types.js';
import { systemClock } from '../db/types.js';
import type { MediaQueue, MediaRecord } from '../media/queue.js';
import type { OperationLog, ServerResult } from '../log/operation-log.js';
import { payloadOf, type OperationRecord } from '../log/types.js';
import { RetrySchedule, type BackoffOptions } from './backoff.js';
import { maySyncText, OFFLINE, type NetworkMonitor, type NetworkState } from './connectivity.js';
import {
  PermanentSyncError,
  TransientSyncError,
  type SyncOperationOut,
  type SyncTransport,
} from './transport.js';

export type SyncReason =
  | 'foreground'
  | 'connectivity'
  | 'background-task'
  | 'manual'
  | 'after-write'
  | 'startup';

export interface SyncProgress {
  readonly done: number;
  readonly total: number;
}

export interface SyncEngineState {
  readonly running: boolean;
  readonly reason: SyncReason | null;
  readonly progress: SyncProgress | null;
  readonly network: NetworkState;
  readonly lastSyncedAt: number | null;
  readonly lastError: string | null;
  readonly nextAttemptAt: number;
  readonly missingSeq: number | null;
}

export interface SyncRunSummary {
  readonly ran: boolean;
  readonly reason: SyncReason;
  readonly operationsSent: number;
  readonly operationsApplied: number;
  readonly mediaUploaded: number;
  readonly missingSeq: number | null;
  readonly skippedBecause: 'offline' | 'backoff' | 'already-running' | null;
  readonly error: string | null;
}

export interface SyncEngineOptions {
  readonly log: OperationLog;
  readonly media: MediaQueue;
  readonly transport: SyncTransport;
  readonly network: NetworkMonitor;
  readonly clock?: Clock;
  readonly backoff?: BackoffOptions;
  /** Operations per batch. 50 (file 22); the server accepts up to 500. */
  readonly batchSize?: number;
  /** Media items per run. Small, because each one can be minutes on a 2G link. */
  readonly mediaPerRun?: number;
}

export class SyncEngine {
  readonly #log: OperationLog;
  readonly #media: MediaQueue;
  readonly #transport: SyncTransport;
  readonly #monitor: NetworkMonitor;
  readonly #clock: Clock;
  readonly #retry: RetrySchedule;
  readonly #batchSize: number;
  readonly #mediaPerRun: number;
  readonly #listeners = new Set<(state: SyncEngineState) => void>();

  #running = false;
  #queuedReason: SyncReason | null = null;
  #reason: SyncReason | null = null;
  #progress: SyncProgress | null = null;
  #network: NetworkState = OFFLINE;
  #lastSyncedAt: number | null = null;
  #lastError: string | null = null;
  #missingSeq: number | null = null;
  #unsubscribeNetwork: (() => void) | null = null;

  constructor(options: SyncEngineOptions) {
    this.#log = options.log;
    this.#media = options.media;
    this.#transport = options.transport;
    this.#monitor = options.network;
    this.#clock = options.clock ?? systemClock;
    this.#retry = new RetrySchedule(options.backoff);
    this.#batchSize = options.batchSize ?? 50;
    this.#mediaPerRun = options.mediaPerRun ?? 3;
  }

  get state(): SyncEngineState {
    return {
      running: this.#running,
      reason: this.#reason,
      progress: this.#progress,
      network: this.#network,
      lastSyncedAt: this.#lastSyncedAt,
      lastError: this.#lastError,
      nextAttemptAt: this.#retry.nextAllowedAt,
      missingSeq: this.#missingSeq,
    };
  }

  subscribe(listener: (state: SyncEngineState) => void): () => void {
    this.#listeners.add(listener);
    listener(this.state);
    return () => this.#listeners.delete(listener);
  }

  #emit(): void {
    const snapshot = this.state;
    for (const listener of this.#listeners) listener(snapshot);
  }

  /**
   * Start watching the network.
   *
   * A connectivity change clears the backoff wait: the reason the last attempt failed has
   * demonstrably changed, so making the device sit out four more minutes would be
   * punishing it for the old network.
   */
  async start(): Promise<void> {
    this.#network = await this.#monitor.current();
    this.#unsubscribeNetwork = this.#monitor.subscribe((state) => {
      const regained = !this.#network.reachable && state.reachable;
      this.#network = state;
      if (regained) {
        this.#retry.allowNow();
        void this.request('connectivity');
      }
      this.#emit();
    });
    this.#emit();
  }

  async stop(): Promise<void> {
    this.#unsubscribeNetwork?.();
    this.#unsubscribeNetwork = null;
  }

  /**
   * Ask for a sync.
   *
   * Returns what happened, including "nothing, and here is why". Every caller in the app
   * ignores the return value; the tests do not, because "it silently did nothing" is the
   * failure this whole class exists to make impossible.
   */
  async request(reason: SyncReason): Promise<SyncRunSummary> {
    if (this.#running) {
      // Remember it rather than drop it. A write that lands mid-run must not wait for the
      // next fifteen-minute background task to be noticed.
      this.#queuedReason = reason;
      return {
        ran: false,
        reason,
        operationsSent: 0,
        operationsApplied: 0,
        mediaUploaded: 0,
        missingSeq: this.#missingSeq,
        skippedBecause: 'already-running',
        error: null,
      };
    }

    const summary = await this.#run(reason);

    const queued = this.#queuedReason;
    this.#queuedReason = null;
    if (queued && summary.ran && summary.error === null) {
      await this.request(queued);
    }
    return summary;
  }

  /** Pull-to-refresh: the one trigger that ignores an outstanding backoff. */
  async refreshNow(): Promise<SyncRunSummary> {
    this.#retry.allowNow();
    return this.request('manual');
  }

  async #run(reason: SyncReason): Promise<SyncRunSummary> {
    // Claimed before the first `await`, not after it. Two triggers firing in the same
    // tick - a foreground event and a connectivity change, which is the normal case on a
    // handset - would otherwise both pass the check in `request` and send one batch twice.
    this.#running = true;
    this.#reason = reason;

    const idle = (skipped: SyncRunSummary['skippedBecause']): SyncRunSummary => {
      this.#running = false;
      this.#reason = null;
      return {
        ran: false,
        reason,
        operationsSent: 0,
        operationsApplied: 0,
        mediaUploaded: 0,
        missingSeq: this.#missingSeq,
        skippedBecause: skipped,
        error: null,
      };
    };

    const now = this.#clock.now();
    this.#network = await this.#monitor.current();

    if (!maySyncText(this.#network)) return idle('offline');
    if (!this.#retry.mayRun(now)) return idle('backoff');

    this.#emit();

    let sent = 0;
    let applied = 0;
    let uploaded = 0;
    let error: string | null = null;

    try {
      const pushed = await this.#pushOperations();
      sent = pushed.sent;
      applied = pushed.applied;

      // Media only after the text is away. On a link that dies after ninety seconds, the
      // assessments are what got through, and that is the right ninety seconds to have
      // spent.
      uploaded = await this.#pushMedia();

      this.#retry.succeed();
      this.#lastSyncedAt = this.#clock.now();
      this.#lastError = null;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
      this.#lastError = error;
      if (cause instanceof PermanentSyncError) {
        // Not retried on a schedule. A malformed batch stays malformed, and the log rows
        // carry the reason for whoever looks at the device.
        this.#retry.succeed();
      } else {
        this.#retry.fail(this.#clock.now());
      }
    } finally {
      this.#running = false;
      this.#reason = null;
      this.#progress = null;
      this.#emit();
    }

    return {
      ran: true,
      reason,
      operationsSent: sent,
      operationsApplied: applied,
      mediaUploaded: uploaded,
      missingSeq: this.#missingSeq,
      skippedBecause: null,
      error,
    };
  }

  async #pushOperations(): Promise<{ sent: number; applied: number }> {
    const device = await this.#log.device();
    let sent = 0;
    let applied = 0;
    /**
     * A hole in this device's own log.
     *
     * Held across the whole run and applied last, because the server cannot see it. A
     * batch that stops one short of a gap looks contiguous from the server's side, so its
     * `missing_seq: null` is a true statement about the batch and a false one about the
     * device. The device's own answer wins.
     */
    let localGap: number | null = null;
    let serverCursor = device.server_cursor;

    // Keep going while the log has contiguous work. A device that has been offline for
    // two days holds more than one batch, and stopping after fifty would mean the officer
    // has to trigger the sync forty times.
    for (;;) {
      const plan = await this.#log.claim(this.#batchSize);

      if (plan.missingSeq !== null) localGap = plan.missingSeq;

      if (plan.operations.length === 0) break;

      this.#progress = { done: sent, total: sent + plan.operations.length };
      this.#emit();

      const assessments = plan.operations.filter((op) => op.entity_type === 'assessment');
      const reports = plan.operations.filter((op) => op.entity_type === 'report');
      const grievances = plan.operations.filter((op) => op.entity_type === 'grievance');
      const unknown = plan.operations.filter(
        (op) =>
          op.entity_type !== 'assessment' &&
          op.entity_type !== 'report' &&
          op.entity_type !== 'grievance',
      );

      try {
        if (assessments.length > 0) {
          const response = await this.#transport.pushAssessments({
            device_id: device.device_id,
            operations: assessments.map(toWire),
          });
          await this.#log.applyResults(response.results);
          serverCursor = response.device_cursor;
          if (response.missing_seq !== null) localGap = response.missing_seq;
          applied += response.applied;
        }

        for (const operation of reports) {
          const result = await this.#submitOne(operation, async (wire) => {
            const created = await this.#transport.submitReport(wire);
            return created.report_id;
          });
          await this.#log.applyResults([result]);
          if (result.status === 'applied') applied += 1;
        }

        for (const operation of grievances) {
          const result = await this.#submitOne(operation, async (wire) => {
            const created = await this.#transport.submitGrievance(wire);
            return created.id;
          });
          await this.#log.applyResults([result]);
          if (result.status === 'applied') applied += 1;
        }

        for (const operation of unknown) {
          // An entity the transport has no route for. Recorded as needing attention
          // rather than dropped: a device holding work nothing will ever send must say so.
          await this.#log.applyResults([
            {
              client_operation_id: operation.client_operation_id,
              status: 'conflict',
              detail:
                `this build has no sync route for ${operation.entity_type}. The device is ` +
                'running against a server it does not match; update the app.',
            },
          ]);
        }
      } catch (cause) {
        await this.#log.release(
          plan.operations.map((operation) => operation.client_operation_id),
          { error: cause instanceof Error ? cause.message : String(cause) },
        );
        throw cause;
      }

      sent += plan.operations.length;
      this.#progress = { done: sent, total: sent };
      this.#emit();

      if (plan.operations.length < this.#batchSize) break;
    }

    this.#missingSeq = localGap;
    await this.#log.recordSync({
      serverCursor,
      missingSeq: localGap,
      error:
        localGap === null
          ? null
          : `the device log is missing seq ${localGap}; everything after it is held`,
    });

    return { sent, applied };
  }

  /**
   * Send one operation that has its own endpoint rather than a batch.
   *
   * A permanent refusal becomes a `conflict` rather than a thrown error: the run carries
   * on with the rest of the queue, and the row that cannot be sent is surfaced to a person
   * instead of blocking everything behind it forever.
   */
  async #submitOne(
    operation: OperationRecord,
    send: (wire: SyncOperationOut) => Promise<string>,
  ): Promise<ServerResult> {
    try {
      const serverId = await send(toWire(operation));
      return {
        client_operation_id: operation.client_operation_id,
        status: 'applied',
        server_id: serverId,
      };
    } catch (cause) {
      if (cause instanceof PermanentSyncError) {
        return {
          client_operation_id: operation.client_operation_id,
          status: 'conflict',
          detail: cause.message,
        };
      }
      throw cause;
    }
  }

  async #pushMedia(): Promise<number> {
    const ready = await this.#media.claimable(this.#network, this.#mediaPerRun);
    let uploaded = 0;

    for (const item of ready) {
      const serverId = await this.#serverIdFor(item);
      if (serverId === null) {
        // The record it belongs to has not synced yet, so there is nothing to attach it
        // to. Left pending: this is the ordering working, not a failure.
        continue;
      }

      await this.#media.markUploading(item.id);
      try {
        const grant = await this.#transport.presignMedia({
          reportId: serverId,
          kind: item.kind,
          contentType: item.content_type,
          sizeBytes: item.size_bytes,
          durationSeconds: item.duration_seconds,
        });
        await this.#transport.putMedia({
          grant,
          localUri: item.local_uri,
          contentType: item.content_type,
          sizeBytes: item.size_bytes,
          resumeFrom: item.bytes_sent,
          onProgress: (bytes) => void this.#media.recordProgress(item.id, bytes),
        });
        await this.#media.markUploaded(item.id, grant.key);
        uploaded += 1;
      } catch (cause) {
        if (cause instanceof PermanentSyncError) {
          await this.#media.markRefused(item.id, cause.message);
          continue;
        }
        await this.#media.markFailed(
          item.id,
          cause instanceof Error ? cause.message : String(cause),
        );
        // A media failure does not fail the run. The text is already away, which is the
        // half that matters, and the photo retries on the next trigger.
        if (cause instanceof TransientSyncError) continue;
        throw cause;
      }
    }

    return uploaded;
  }

  /** The server id of the record a media item hangs off, if it has one yet. */
  async #serverIdFor(item: MediaRecord): Promise<string | null> {
    const operation = await this.#log.byId(item.client_operation_id);
    return operation?.server_id ?? null;
  }
}

function toWire(record: OperationRecord): SyncOperationOut {
  return {
    client_operation_id: record.client_operation_id,
    op: record.op,
    seq: record.seq,
    target: record.server_id,
    payload: payloadOf(record),
  };
}
