/**
 * The wire, as a port.
 *
 * The shapes below are the server's, copied field for field from
 * `ledger_svc.api.v1.assessments` and `incident_svc.api.v1.reports`. They are not
 * remodelled on the way through: a device that renames `client_operation_id` on its way
 * out has to rename it on the way back, and the sync contract's whole safety property is
 * that the same key means the same operation at both ends.
 */

import type { ServerResult } from '../log/operation-log.js';

export interface SyncOperationOut {
  readonly client_operation_id: string;
  readonly op: 'create' | 'update';
  readonly seq: number;
  readonly target?: string | null;
  readonly payload: Record<string, unknown>;
}

export interface SyncRequest {
  readonly device_id: string;
  readonly operations: readonly SyncOperationOut[];
}

export interface SyncResponse {
  readonly device_id: string;
  readonly results: readonly ServerResult[];
  readonly applied: number;
  readonly device_cursor: number;
  /** Set when a gap paused this device. Send this seq, then retry. */
  readonly missing_seq: number | null;
}

/** `POST /api/v1/reports/{id}/media` - the grant, issued before any bytes move. */
export interface MediaGrant {
  readonly key: string;
  readonly content_type: string;
  readonly max_bytes: number;
  readonly expires_in: number;
}

export interface MediaUpload {
  readonly grant: MediaGrant;
  readonly localUri: string;
  readonly contentType: string;
  readonly sizeBytes: number;
  /** Where a previous attempt stopped. Zero on the first try. */
  readonly resumeFrom: number;
  readonly onProgress?: (bytesSent: number) => void;
  readonly signal?: AbortSignal;
}

/**
 * Everything the sync engine needs from the network.
 *
 * One interface rather than a client, because every test in this package drives the
 * engine through a fake that can fail mid-batch, time out, return a gap, or return a
 * conflict - and each of those is a case the brief names.
 */
export interface SyncTransport {
  /** Push a batch of operations. Safe to call with the same batch twice. */
  pushAssessments(request: SyncRequest): Promise<SyncResponse>;
  /**
   * Submit one citizen report.
   *
   * Reports do not go through `/sync`: incident-svc takes them one at a time with an
   * `Idempotency-Key`, because a report can become a dispatch and a batch endpoint that
   * half-succeeds would be a dispatcher's problem rather than a device's.
   */
  submitReport(
    operation: SyncOperationOut,
  ): Promise<{ report_id: string; incident_id: string | null; public_ref: string | null }>;
  /**
   * Raise one grievance.
   *
   * Also one at a time, and for a sharper reason than reports: raising the same grievance
   * twice starts two SLA clocks against one household and puts two DS officers on one
   * dispute. `client_operation_id` is the idempotency key, so a replay is the same
   * grievance.
   */
  submitGrievance(
    operation: SyncOperationOut,
  ): Promise<{ id: string; public_ref: string; sla_due_at: string }>;
  /** Ask for permission to upload, and where to put it. */
  presignMedia(input: {
    reportId: string;
    kind: 'photo' | 'audio';
    contentType: string;
    sizeBytes: number;
    durationSeconds?: number | null;
  }): Promise<MediaGrant>;
  /** Send the bytes. Resumable; reports progress so an interruption is not a restart. */
  putMedia(upload: MediaUpload): Promise<void>;
}

/** A transport failure that is worth retrying: no signal, a timeout, a 5xx. */
export class TransientSyncError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = 'TransientSyncError';
  }
}

/**
 * A refusal the device cannot fix by retrying.
 *
 * A 422 on a batch means the batch is malformed - a repeated seq, an oversized push.
 * Retrying sends the same malformed batch, so it is surfaced instead.
 */
export class PermanentSyncError extends Error {
  constructor(message: string, readonly cause?: unknown) {
    super(message);
    this.name = 'PermanentSyncError';
  }
}
