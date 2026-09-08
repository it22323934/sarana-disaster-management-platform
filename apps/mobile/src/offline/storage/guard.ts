/**
 * Storage limits, and what the app does when it runs into them.
 *
 * The failure this exists to prevent is specific and it has happened to every field app
 * ever built: a device fills up, the camera returns a zero-byte file, the form saves
 * happily, and the officer finds out three days later that forty assessments have no
 * photographs. Silence is the bug. Every branch here produces a message.
 */

const MB = 1024 * 1024;

/** Below this, the app says so but keeps working. */
export const WARN_FREE_BYTES = 200 * MB;

/** Below this, photo capture is refused up front rather than allowed to fail. */
export const REFUSE_FREE_BYTES = 50 * MB;

/** The media cache ceiling. Synced items are evicted oldest-first to stay under it. */
export const MEDIA_CACHE_LIMIT_BYTES = 500 * MB;

/**
 * The largest a single compressed photo is expected to be.
 *
 * 1600px at quality 0.7 lands well under this in practice; the headroom is what stops a
 * capture being accepted at 51MB free and then failing at 49.
 */
export const PHOTO_HEADROOM_BYTES = 8 * MB;

export type StorageLevel = 'ok' | 'low' | 'critical';

export interface StorageState {
  readonly freeBytes: number;
  readonly mediaCacheBytes: number;
}

export interface StorageVerdict {
  readonly level: StorageLevel;
  /** Whether the camera may be opened at all. */
  readonly mayCapture: boolean;
  /** The i18n key for what to tell the user. Null when there is nothing to say. */
  readonly messageKey: string | null;
  readonly values: Readonly<Record<string, number>>;
}

export function assessStorage(state: StorageState): StorageVerdict {
  const freeMb = Math.floor(state.freeBytes / MB);

  if (state.freeBytes < REFUSE_FREE_BYTES) {
    return {
      level: 'critical',
      mayCapture: false,
      // Names the number and the action. "Storage full" alone leaves an officer holding
      // a phone in the rain with nothing to do about it.
      messageKey: 'storage.criticalRefusePhoto',
      values: { freeMb },
    };
  }

  if (state.freeBytes < WARN_FREE_BYTES) {
    return {
      level: 'low',
      mayCapture: true,
      messageKey: 'storage.lowWarning',
      values: { freeMb },
    };
  }

  return { level: 'ok', mayCapture: true, messageKey: null, values: {} };
}

/** One item in the media cache, as far as eviction is concerned. */
export interface EvictionCandidate {
  readonly id: string;
  readonly size_bytes: number;
  readonly created_at: string;
  readonly status: string;
}

/**
 * Which cached media to delete to get back under the cap.
 *
 * **Only uploaded items are ever evicted.** Deleting a photo that has not reached the
 * server destroys the only copy of evidence attached to a household's damage claim, and
 * no cache pressure justifies that. If the uploaded items are not enough to get under the
 * cap, the cap is exceeded and the caller is told - the answer to a full disk is to stop
 * accepting new photos, which `assessStorage` already does.
 */
export function plannedEvictions(
  candidates: readonly EvictionCandidate[],
  { cacheBytes, limitBytes = MEDIA_CACHE_LIMIT_BYTES }: { cacheBytes: number; limitBytes?: number },
): { evict: EvictionCandidate[]; reclaimed: number; stillOver: boolean } {
  if (cacheBytes <= limitBytes) return { evict: [], reclaimed: 0, stillOver: false };

  const evictable = candidates
    .filter((item) => item.status === 'uploaded')
    .sort((a, b) => a.created_at.localeCompare(b.created_at));

  const evict: EvictionCandidate[] = [];
  let reclaimed = 0;
  for (const item of evictable) {
    if (cacheBytes - reclaimed <= limitBytes) break;
    evict.push(item);
    reclaimed += item.size_bytes;
  }

  return { evict, reclaimed, stillOver: cacheBytes - reclaimed > limitBytes };
}
