/**
 * The fakes the offline core is driven against.
 *
 * `FakeServer` is not a stub that returns a canned response. It re-implements the
 * server's sync contract - the cursor, the idempotency set, the gap rule - closely enough
 * that a device bug shows up here as the wrong number of stored assessments, which is
 * the shape the bug takes in production. Where it and `ledger_svc.domain.sync.plan`
 * disagree, the Python one is right and this file is the bug.
 */

import type {
  MediaGrant,
  MediaUpload,
  SyncOperationOut,
  SyncRequest,
  SyncResponse,
  SyncTransport,
} from '../src/offline/sync/transport.js';
import { PermanentSyncError, TransientSyncError } from '../src/offline/sync/transport.js';
import type { ServerResult } from '../src/offline/log/operation-log.js';
import type { NetworkMonitor, NetworkState } from '../src/offline/sync/connectivity.js';
import type { Clock } from '../src/offline/db/types.js';

export const WIFI: NetworkState = {
  connected: true,
  reachable: true,
  kind: 'wifi',
  metered: false,
};

export const CELLULAR: NetworkState = {
  connected: true,
  reachable: true,
  kind: 'cellular',
  metered: true,
};

export const AIRPLANE: NetworkState = {
  connected: false,
  reachable: false,
  kind: 'none',
  metered: false,
};

/** A captive portal: an interface is up and nothing on the internet answers. */
export const CAPTIVE_PORTAL: NetworkState = {
  connected: true,
  reachable: false,
  kind: 'wifi',
  metered: false,
};

export class FakeNetwork implements NetworkMonitor {
  #state: NetworkState;
  readonly #listeners = new Set<(state: NetworkState) => void>();

  constructor(state: NetworkState = WIFI) {
    this.#state = state;
  }

  async current(): Promise<NetworkState> {
    return this.#state;
  }

  subscribe(listener: (state: NetworkState) => void): () => void {
    this.#listeners.add(listener);
    return () => this.#listeners.delete(listener);
  }

  set(state: NetworkState): void {
    this.#state = state;
    for (const listener of this.#listeners) listener(state);
  }
}

export class TestClock implements Clock {
  constructor(private ms: number = Date.UTC(2026, 8, 8, 6, 0, 0)) {}

  now(): number {
    return this.ms;
  }

  advance(ms: number): void {
    this.ms += ms;
  }

  set(ms: number): void {
    this.ms = ms;
  }
}

interface StoredAssessment {
  readonly serverId: string;
  readonly clientOperationId: string;
  readonly seq: number;
  readonly payload: Record<string, unknown>;
}

/**
 * The half of ledger-svc and incident-svc a field device can see.
 *
 * Failures are scripted rather than random: `failNextPush` makes the next batch throw
 * after the server has already applied it, which is precisely the case the idempotency
 * key exists for and the one a random failure would only occasionally produce.
 */
export class FakeServer implements SyncTransport {
  readonly assessments = new Map<string, StoredAssessment>();
  readonly reports = new Map<string, Record<string, unknown>>();
  readonly media = new Map<string, { key: string; bytes: number }>();
  readonly grievances = new Map<
    string,
    { id: string; public_ref: string; sla_due_at: string }
  >();

  /** Per-device sync cursor, exactly as `ledger.device_sync_cursor` holds it. */
  readonly cursors = new Map<string, number>();

  pushCalls = 0;
  reportCalls = 0;
  grievanceCalls = 0;

  /** Throw on the next push, *after* applying it. Models a dropped response. */
  failNextPushAfterApply = false;
  /** Throw on the next push before applying anything. Models a dropped request. */
  failNextPushBeforeApply = false;
  /** Refuse the next media presign permanently. Models an oversized photo. */
  refuseNextMedia = false;
  /** Throw a transient error on the next media upload. */
  failNextMediaUpload = false;
  /** Interrupt an upload after this many bytes, then succeed on the retry. */
  interruptUploadAfter: number | null = null;

  async pushAssessments(request: SyncRequest): Promise<SyncResponse> {
    this.pushCalls += 1;

    if (this.failNextPushBeforeApply) {
      this.failNextPushBeforeApply = false;
      throw new TransientSyncError('the connection dropped before the request was sent');
    }

    const cursor = this.cursors.get(request.device_id) ?? 0;
    const { results, appliedSeq, missing, applied } = this.#plan(request, cursor);
    this.cursors.set(request.device_id, appliedSeq);

    if (this.failNextPushAfterApply) {
      this.failNextPushAfterApply = false;
      // Applied, then the response never arrived. The device retries the whole batch and
      // must not produce a second copy of anything.
      throw new TransientSyncError('the connection dropped while the response was in flight');
    }

    return {
      device_id: request.device_id,
      results,
      applied,
      device_cursor: appliedSeq,
      missing_seq: missing,
    };
  }

  /** A transcription of `ledger_svc.domain.sync.plan`, plus the writes the endpoint does. */
  #plan(
    request: SyncRequest,
    cursor: number,
  ): { results: ServerResult[]; appliedSeq: number; missing: number | null; applied: number } {
    const seen = new Set<number>();
    for (const operation of request.operations) {
      if (seen.has(operation.seq)) {
        throw new PermanentSyncError(
          `seq ${operation.seq} appears twice in this batch; the device log is append-only`,
        );
      }
      seen.add(operation.seq);
    }

    const ordered = [...request.operations].sort((a, b) => a.seq - b.seq);
    const results: ServerResult[] = [];
    let expected = cursor + 1;
    let appliedSeq = cursor;
    let missing: number | null = null;
    let applied = 0;

    for (const operation of ordered) {
      if (missing !== null) {
        results.push({
          client_operation_id: operation.client_operation_id,
          status: 'blocked',
          detail: `held: this device has not sent seq ${missing}.`,
        });
        continue;
      }

      const stored = this.assessments.get(operation.client_operation_id);
      if (stored) {
        results.push({
          client_operation_id: operation.client_operation_id,
          status: 'duplicate',
          server_id: stored.serverId,
        });
        appliedSeq = Math.max(appliedSeq, operation.seq);
        expected = Math.max(expected, operation.seq + 1);
        continue;
      }

      if (operation.seq < expected) {
        results.push({
          client_operation_id: operation.client_operation_id,
          status: 'conflict',
          conflict: { reason: 'seq_already_consumed', seq: operation.seq },
          detail: `seq ${operation.seq} was already applied from a different operation.`,
        });
        continue;
      }

      if (operation.seq > expected) {
        missing = expected;
        results.push({
          client_operation_id: operation.client_operation_id,
          status: 'blocked',
          detail: `held: this device has not sent seq ${missing}.`,
        });
        continue;
      }

      const serverId = `srv_${this.assessments.size + 1}`;
      this.assessments.set(operation.client_operation_id, {
        serverId,
        clientOperationId: operation.client_operation_id,
        seq: operation.seq,
        payload: operation.payload,
      });
      results.push({
        client_operation_id: operation.client_operation_id,
        status: 'applied',
        server_id: serverId,
      });
      applied += 1;
      appliedSeq = Math.max(appliedSeq, operation.seq);
      expected += 1;
    }

    return { results, appliedSeq, missing, applied };
  }

  async submitReport(
    operation: SyncOperationOut,
  ): Promise<{ report_id: string; incident_id: string | null; public_ref: string | null }> {
    this.reportCalls += 1;
    const existing = this.reports.get(operation.client_operation_id);
    if (existing) {
      return existing as { report_id: string; incident_id: string | null; public_ref: string | null };
    }
    const created = {
      report_id: `rep_${this.reports.size + 1}`,
      incident_id: `inc_${this.reports.size + 1}`,
      public_ref: `INC-${this.reports.size + 1}`,
    };
    this.reports.set(operation.client_operation_id, created);
    return created;
  }

  async submitGrievance(
    operation: SyncOperationOut,
  ): Promise<{ id: string; public_ref: string; sla_due_at: string }> {
    this.grievanceCalls += 1;
    const existing = this.grievances.get(operation.client_operation_id);
    if (existing) return existing;
    const created = {
      id: `grv_${this.grievances.size + 1}`,
      public_ref: `GRV-${this.grievances.size + 1}`,
      sla_due_at: '2026-09-22T00:00:00Z',
    };
    this.grievances.set(operation.client_operation_id, created);
    return created;
  }

  async presignMedia(input: {
    reportId: string;
    kind: 'photo' | 'audio';
    contentType: string;
    sizeBytes: number;
  }): Promise<MediaGrant> {
    if (this.refuseNextMedia) {
      this.refuseNextMedia = false;
      throw new PermanentSyncError(
        `${input.contentType} at ${input.sizeBytes} bytes is larger than a photo may be`,
      );
    }
    return {
      key: `2026/09/08/${input.reportId}/${this.media.size + 1}`,
      content_type: input.contentType,
      max_bytes: 5 * 1024 * 1024,
      expires_in: 900,
    };
  }

  async putMedia(upload: MediaUpload): Promise<void> {
    if (this.failNextMediaUpload) {
      this.failNextMediaUpload = false;
      throw new TransientSyncError('the upload timed out');
    }
    if (this.interruptUploadAfter !== null) {
      const stopAt = this.interruptUploadAfter;
      this.interruptUploadAfter = null;
      upload.onProgress?.(stopAt);
      throw new TransientSyncError(`the upload stopped after ${stopAt} bytes`);
    }
    upload.onProgress?.(upload.sizeBytes);
    this.media.set(upload.grant.key, { key: upload.grant.key, bytes: upload.sizeBytes });
  }
}
