/**
 * The media queue: a second, resumable queue that runs behind the operation log.
 *
 * The separation is the point. A 4MB photo on a 2G link takes minutes; a 200-byte
 * assessment record takes a second. Putting them in one queue means the record waits for
 * the photo, and the reviewer in the district office sees nothing at all until the whole
 * upload finishes. Metadata first, evidence behind it, linked by `client_operation_id`.
 *
 * Uploads are resumable because they are expected to be interrupted. `bytes_sent` is kept
 * so a photo that got 80% of the way up a cell-edge link does not start again from zero
 * the next time the officer walks past a window.
 */

import { deviceUuid7 } from '../ids.js';
import type { Clock, Database } from '../db/types.js';
import { systemClock } from '../db/types.js';
import type { MediaCounts } from '../status/model.js';
import { mediaPolicy, type NetworkState } from '../sync/connectivity.js';
import {
  MEDIA_CACHE_LIMIT_BYTES,
  plannedEvictions,
  type EvictionCandidate,
} from '../storage/guard.js';

export type MediaKind = 'photo' | 'audio';

export type MediaStatus =
  | 'pending'
  | 'deferred'
  | 'uploading'
  | 'uploaded'
  | 'failed'
  | 'refused';

export interface MediaRecord {
  readonly id: string;
  readonly client_operation_id: string;
  readonly entity_type: string;
  readonly entity_local_id: string;
  readonly kind: MediaKind;
  readonly local_uri: string;
  readonly content_type: string;
  readonly size_bytes: number;
  readonly duration_seconds: number | null;
  readonly sha256: string | null;
  readonly latitude: number | null;
  readonly longitude: number | null;
  readonly created_at: string;
  readonly status: MediaStatus;
  readonly attempt_count: number;
  readonly bytes_sent: number;
  readonly remote_key: string | null;
  readonly last_error: string | null;
  readonly uploaded_at: string | null;
}

export interface NewMedia {
  readonly client_operation_id: string;
  readonly entity_type: string;
  readonly entity_local_id: string;
  readonly kind: MediaKind;
  readonly local_uri: string;
  readonly content_type: string;
  readonly size_bytes: number;
  readonly duration_seconds?: number | null;
  readonly sha256?: string | null;
  /**
   * Where the photo was taken.
   *
   * Lifted out of the file's EXIF and then stripped from the file itself (file 22's
   * battery and resilience section). The coordinate is evidence and belongs in a column
   * a reviewer can see; leaving it embedded in an image that may later be shown to the
   * public is how a household's address leaks.
   */
  readonly latitude?: number | null;
  readonly longitude?: number | null;
  /** Set by the user for this one item. Sends it over a metered link. */
  readonly urgent?: boolean;
}

const COLUMNS =
  'id, client_operation_id, entity_type, entity_local_id, kind, local_uri, content_type, ' +
  'size_bytes, duration_seconds, sha256, latitude, longitude, created_at, status, ' +
  'attempt_count, bytes_sent, remote_key, last_error, uploaded_at';

export const EMPTY_MEDIA: MediaCounts = {
  pending: 0,
  deferred: 0,
  uploading: 0,
  failed: 0,
};

export class MediaQueue {
  /** Per-item urgency. Not persisted: it is a decision about this upload, not the file. */
  readonly #urgent = new Set<string>();

  constructor(
    private readonly db: Database,
    private readonly clock: Clock = systemClock,
  ) {}

  async enqueue(media: NewMedia): Promise<MediaRecord> {
    const now = this.clock.now();
    const id = deviceUuid7(now);
    await this.db.execute(
      `INSERT INTO media_upload (${COLUMNS}) ` +
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, NULL)',
      [
        id,
        media.client_operation_id,
        media.entity_type,
        media.entity_local_id,
        media.kind,
        media.local_uri,
        media.content_type,
        media.size_bytes,
        media.duration_seconds ?? null,
        media.sha256 ?? null,
        media.latitude ?? null,
        media.longitude ?? null,
        new Date(now).toISOString(),
        'pending' satisfies MediaStatus,
      ],
    );
    if (media.urgent) this.#urgent.add(id);
    return (await this.byId(id))!;
  }

  async byId(id: string): Promise<MediaRecord | null> {
    const [row] = await this.db.select<MediaRecord>(
      `SELECT ${COLUMNS} FROM media_upload WHERE id = ?`,
      [id],
    );
    return row ?? null;
  }

  async forOperation(clientOperationId: string): Promise<MediaRecord[]> {
    return this.db.select<MediaRecord>(
      `SELECT ${COLUMNS} FROM media_upload WHERE client_operation_id = ? ORDER BY created_at`,
      [clientOperationId],
    );
  }

  isUrgent(id: string): boolean {
    return this.#urgent.has(id);
  }

  /** Mark one item urgent, so it goes over a metered link. */
  markUrgent(id: string): void {
    this.#urgent.add(id);
  }

  /**
   * What may be uploaded on this network, oldest first.
   *
   * Items the policy defers are moved to `deferred` rather than skipped, so the status
   * strip can say "waiting for Wi-Fi" instead of leaving them looking stuck. They come
   * back to `pending` the moment a Wi-Fi connection appears.
   */
  async claimable(network: NetworkState, limit = 3): Promise<MediaRecord[]> {
    const rows = await this.db.select<MediaRecord>(
      `SELECT ${COLUMNS} FROM media_upload ` +
        "WHERE status IN ('pending', 'deferred', 'failed') ORDER BY created_at LIMIT ?",
      [limit * 4],
    );

    const ready: MediaRecord[] = [];
    for (const row of rows) {
      const policy = mediaPolicy({ network, urgent: this.#urgent.has(row.id) });
      if (policy === 'send') {
        if (row.status === 'deferred') await this.#setStatus(row.id, 'pending');
        ready.push(row);
        if (ready.length >= limit) break;
      } else if (row.status === 'pending') {
        await this.#setStatus(row.id, 'deferred');
      }
    }
    return ready;
  }

  async markUploading(id: string): Promise<void> {
    await this.db.execute(
      'UPDATE media_upload SET status = ?, attempt_count = attempt_count + 1 WHERE id = ?',
      ['uploading' satisfies MediaStatus, id],
    );
  }

  /** Record partial progress so an interrupted upload resumes rather than restarts. */
  async recordProgress(id: string, bytesSent: number): Promise<void> {
    await this.db.execute('UPDATE media_upload SET bytes_sent = ? WHERE id = ?', [bytesSent, id]);
  }

  async markUploaded(id: string, remoteKey: string): Promise<void> {
    await this.db.execute(
      'UPDATE media_upload SET status = ?, remote_key = ?, uploaded_at = ?, last_error = NULL ' +
        'WHERE id = ?',
      [
        'uploaded' satisfies MediaStatus,
        remoteKey,
        new Date(this.clock.now()).toISOString(),
        id,
      ],
    );
    this.#urgent.delete(id);
  }

  async markFailed(id: string, error: string, { failAfter = 5 } = {}): Promise<void> {
    await this.db.execute(
      'UPDATE media_upload SET status = CASE WHEN attempt_count >= ? THEN ? ELSE ? END, ' +
        'last_error = ? WHERE id = ?',
      [
        failAfter,
        'failed' satisfies MediaStatus,
        'pending' satisfies MediaStatus,
        error,
        id,
      ],
    );
  }

  /**
   * The server refused it before any bytes moved.
   *
   * A refusal is terminal - the file is too large or the type is not accepted, and
   * retrying sends the same file to the same rule. It is surfaced, not retried.
   */
  async markRefused(id: string, detail: string): Promise<void> {
    await this.db.execute('UPDATE media_upload SET status = ?, last_error = ? WHERE id = ?', [
      'refused' satisfies MediaStatus,
      detail,
      id,
    ]);
  }

  async #setStatus(id: string, status: MediaStatus): Promise<void> {
    await this.db.execute('UPDATE media_upload SET status = ? WHERE id = ?', [status, id]);
  }

  async counts(): Promise<MediaCounts> {
    const rows = await this.db.select<{ status: MediaStatus; n: number }>(
      'SELECT status, COUNT(*) AS n FROM media_upload GROUP BY status',
    );
    const counts = { ...EMPTY_MEDIA } as { -readonly [K in keyof MediaCounts]: number };
    for (const row of rows) {
      // `refused` is counted with `failed`: both need a person, and the strip's job is to
      // say how many things need one, not to teach the user the difference.
      if (row.status === 'failed' || row.status === 'refused') counts.failed += row.n;
      else if (row.status === 'pending') counts.pending = row.n;
      else if (row.status === 'deferred') counts.deferred = row.n;
      else if (row.status === 'uploading') counts.uploading = row.n;
    }
    return counts;
  }

  async cacheBytes(): Promise<number> {
    const [row] = await this.db.select<{ total: number | null }>(
      'SELECT SUM(size_bytes) AS total FROM media_upload',
    );
    return row?.total ?? 0;
  }

  /**
   * Delete uploaded media to get the cache back under its cap.
   *
   * Returns the rows to remove from disk. The caller deletes the files, because file
   * removal is a platform call and this class owns only the database.
   */
  async evict(limitBytes = MEDIA_CACHE_LIMIT_BYTES): Promise<{
    removed: MediaRecord[];
    stillOver: boolean;
  }> {
    const cacheBytes = await this.cacheBytes();
    const candidates = await this.db.select<EvictionCandidate & MediaRecord>(
      `SELECT ${COLUMNS} FROM media_upload ORDER BY created_at`,
    );

    const plan = plannedEvictions(candidates, { cacheBytes, limitBytes });
    const removed: MediaRecord[] = [];
    for (const item of plan.evict) {
      await this.db.execute('DELETE FROM media_upload WHERE id = ?', [item.id]);
      removed.push(candidates.find((candidate) => candidate.id === item.id)!);
    }
    return { removed, stillOver: plan.stillOver };
  }
}
