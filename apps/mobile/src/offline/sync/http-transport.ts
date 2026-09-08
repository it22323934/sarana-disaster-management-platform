/**
 * The `SyncTransport` over the real services.
 *
 * A thin adapter, on purpose. It maps HTTP failures onto the two categories the engine
 * knows about - retry this, or stop and tell someone - and does nothing else. Every rule
 * about *what* to send lives in the engine, where it is tested without a network.
 *
 * The category split matters more than it looks. A 5xx or a timeout is weather: retry.
 * A 422 on a batch means the batch is malformed, and retrying sends the same malformed
 * batch forever while the officer watches a counter that never moves.
 */

import { SaranaApiError, type SaranaClient } from '@sarana/ts-shared';

import {
  PermanentSyncError,
  TransientSyncError,
  type MediaGrant,
  type MediaUpload,
  type SyncOperationOut,
  type SyncRequest,
  type SyncResponse,
  type SyncTransport,
} from './transport.js';

/** Turn an API failure into the one distinction the engine acts on. */
function classify(cause: unknown, context: string): Error {
  if (cause instanceof SaranaApiError) {
    if (cause.isRetryable) return new TransientSyncError(`${context}: ${cause.message}`, cause);
    if (cause.status === 401 || cause.status === 403) {
      // The client already retried once behind a refresh. A second 401 means the session
      // is gone, and continuing to hammer the endpoint achieves nothing.
      return new PermanentSyncError(`${context}: ${cause.message}`, cause);
    }
    return new PermanentSyncError(`${context}: ${cause.message}`, cause);
  }
  return new TransientSyncError(`${context}: ${String(cause)}`, cause);
}

export interface HttpTransportOptions {
  readonly client: SaranaClient;
  /** Uploads bypass the JSON client: they are raw bytes to object storage. */
  readonly fetch?: typeof globalThis.fetch;
  /** Where a presigned PUT goes. Null until an object store is configured. */
  readonly objectStoreBaseUrl?: string | null;
}

export class HttpSyncTransport implements SyncTransport {
  readonly #client: SaranaClient;
  readonly #fetch: typeof globalThis.fetch;
  readonly #objectStore: string | null;

  constructor(options: HttpTransportOptions) {
    this.#client = options.client;
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#objectStore = options.objectStoreBaseUrl ?? null;
  }

  async pushAssessments(request: SyncRequest): Promise<SyncResponse> {
    try {
      return (await this.#client.post('/api/v1/assessments/sync', {
        body: request,
      })) as SyncResponse;
    } catch (cause) {
      throw classify(cause, 'assessment sync');
    }
  }

  async submitReport(
    operation: SyncOperationOut,
  ): Promise<{ report_id: string; incident_id: string | null; public_ref: string | null }> {
    try {
      return (await this.#client.post('/api/v1/reports', {
        body: operation.payload,
        // The device's operation id *is* the idempotency key. A retry on a failing
        // network must not become a second emergency in the dispatcher's queue.
        idempotencyKey: operation.client_operation_id,
      })) as { report_id: string; incident_id: string | null; public_ref: string | null };
    } catch (cause) {
      throw classify(cause, 'report submission');
    }
  }

  async submitGrievance(
    operation: SyncOperationOut,
  ): Promise<{ id: string; public_ref: string; sla_due_at: string }> {
    try {
      return (await this.#client.post('/api/v1/grievances', {
        body: operation.payload,
        idempotencyKey: operation.client_operation_id,
      })) as { id: string; public_ref: string; sla_due_at: string };
    } catch (cause) {
      throw classify(cause, 'grievance');
    }
  }

  async presignMedia(input: {
    reportId: string;
    kind: 'photo' | 'audio';
    contentType: string;
    sizeBytes: number;
    durationSeconds?: number | null;
  }): Promise<MediaGrant> {
    try {
      return (await this.#client.post(`/api/v1/reports/${input.reportId}/media`, {
        body: {
          kind: input.kind,
          content_type: input.contentType,
          size_bytes: input.sizeBytes,
          duration_seconds: input.durationSeconds ?? undefined,
        },
      })) as MediaGrant;
    } catch (cause) {
      throw classify(cause, 'media presign');
    }
  }

  /**
   * Send the bytes.
   *
   * **This is a stub, and it says so.** incident-svc grants an object key and a size
   * limit; it does not yet sign a PUT, and no object store is wired (see the media
   * handling gap carried since file 08). Until one is, an upload cannot succeed, and the
   * honest failure is a named one that the media queue records against the item rather
   * than a silent success that leaves an assessment claiming evidence it does not have.
   */
  async putMedia(upload: MediaUpload): Promise<void> {
    if (this.#objectStore === null) {
      throw new PermanentSyncError(
        'no object store is configured, so this photo cannot be uploaded. The grant was ' +
          'issued and the file is still on the device; it will upload when a store is ' +
          'wired. Nothing has been lost.',
      );
    }

    const url = `${this.#objectStore.replace(/\/+$/, '')}/${upload.grant.key}`;
    try {
      const response = await this.#fetch(url, {
        method: 'PUT',
        headers: {
          'Content-Type': upload.contentType,
          'Content-Length': String(upload.sizeBytes),
        },
        body: await (await this.#fetch(upload.localUri)).blob(),
        signal: upload.signal,
      });
      if (!response.ok) {
        throw response.status >= 500
          ? new TransientSyncError(`upload failed with ${response.status}`)
          : new PermanentSyncError(`upload refused with ${response.status}`);
      }
      upload.onProgress?.(upload.sizeBytes);
    } catch (cause) {
      if (cause instanceof TransientSyncError || cause instanceof PermanentSyncError) throw cause;
      throw classify(cause, 'media upload');
    }
  }
}
