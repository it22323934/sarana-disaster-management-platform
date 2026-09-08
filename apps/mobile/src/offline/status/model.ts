/**
 * The offline status strip, as a value.
 *
 * The brief calls this "arguably the most important component in the mobile app", and the
 * reason is a question: **is my work safe?** A GN officer in a flooded division has to be
 * able to answer it in under a second, at a glance, without tapping anything. So the strip
 * is persistent, non-dismissible, and never shows a spinner without a number beside it.
 *
 * The rendering lives in `components/SyncStatusStrip.tsx`. Everything that decides *what*
 * it says is here, as a pure function over four inputs, because the wrong answer to that
 * question is how an officer walks away from a device holding a day of unsynced work.
 *
 * The four states, and the shapes the brief specifies:
 *
 *     ● Online · all synced
 *     ◐ Online · syncing 3 of 12
 *     ○ Offline · 12 changes queued · last synced 4h ago
 *     ▲ 2 items need attention
 */

import type { LogCounts } from '../log/operation-log.js';
import type { NetworkState } from '../sync/connectivity.js';

export type StatusTone = 'synced' | 'syncing' | 'offline' | 'attention';

/** The glyph, kept beside the tone so colour is never the only difference. */
export const STATUS_GLYPH: Record<StatusTone, string> = {
  synced: '●', // ●
  syncing: '◐', // ◐
  offline: '○', // ○
  attention: '▲', // ▲
};

export interface MediaCounts {
  readonly pending: number;
  readonly deferred: number;
  readonly uploading: number;
  readonly failed: number;
}

export const EMPTY_MEDIA_COUNTS: MediaCounts = {
  pending: 0,
  deferred: 0,
  uploading: 0,
  failed: 0,
};

export interface StatusInput {
  readonly network: NetworkState;
  readonly operations: LogCounts;
  readonly media: MediaCounts;
  readonly lastSyncedAt: number | null;
  readonly now: number;
  /**
   * What the current sync run has got through, if one is running.
   *
   * Supplied by the engine because it is the only thing that knows the denominator: how
   * much was queued when this run started. Counting it from the log instead would make
   * the total shrink as the run progressed, so "3 of 12" would become "3 of 9" - which
   * reads as the work disappearing rather than as progress.
   */
  readonly progress?: { readonly done: number; readonly total: number } | null;
}

export interface StatusStrip {
  readonly tone: StatusTone;
  readonly glyph: string;
  /**
   * The i18n key for the sentence. The strip never contains an English literal - it is
   * the one component every user sees on every screen, in whichever of three languages
   * they chose at first launch.
   */
  readonly messageKey: string;
  /** Substitutions for the message. Numbers, never prose. */
  readonly values: Readonly<Record<string, string | number>>;
  /** Unsynced operations plus queued media. What "queued" means to a person. */
  readonly queued: number;
  /** Rows that will not move without a person. */
  readonly attention: number;
  /**
   * Whether the strip must be announced when it changes.
   *
   * Screen readers get told about work moving from unsafe to safe and about anything
   * that needs a decision. They do not get told about the counter ticking down, which
   * would talk over the officer for the length of a sync.
   */
  readonly announce: boolean;
}

/** Rounded to something a person reads at a glance. Exact minutes help nobody here. */
export function describeAge(ms: number): { key: string; value: number } {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return { key: 'justNow', value: 0 };
  if (minutes < 60) return { key: 'minutes', value: minutes };
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return { key: 'hours', value: hours };
  return { key: 'days', value: Math.floor(hours / 24) };
}

/**
 * What the strip says right now.
 *
 * Order matters and is the substance of this function. Attention beats everything,
 * including being offline: an officer whose device is holding two conflicts needs to know
 * that whether or not there is a signal, because the fix is on the device. Offline beats
 * syncing, because "syncing 3 of 12" on a dead network is a lie.
 */
export function statusStrip(input: StatusInput): StatusStrip {
  const { operations, media, network, now, lastSyncedAt } = input;

  const attention = operations.conflict + operations.failed + media.failed;
  const unsyncedOperations = operations.pending + operations.syncing + operations.blocked;
  const queuedMedia = media.pending + media.deferred + media.uploading;
  const queued = unsyncedOperations + queuedMedia;

  if (attention > 0) {
    return {
      tone: 'attention',
      glyph: STATUS_GLYPH.attention,
      messageKey: 'sync.status.attention',
      values: { count: attention },
      queued,
      attention,
      announce: true,
    };
  }

  if (!network.reachable) {
    if (queued === 0) {
      return {
        tone: 'offline',
        glyph: STATUS_GLYPH.offline,
        messageKey: 'sync.status.offlineClear',
        values: {},
        queued: 0,
        attention: 0,
        announce: false,
      };
    }
    const age = lastSyncedAt === null ? null : describeAge(now - lastSyncedAt);
    return {
      tone: 'offline',
      glyph: STATUS_GLYPH.offline,
      // Two messages, not one with an optional clause: "last synced never" is a
      // different and more alarming sentence than "last synced 4h ago", and a device
      // that has never synced is exactly the one whose officer needs to be told.
      messageKey: age === null ? 'sync.status.offlineNeverSynced' : `sync.status.offline.${age.key}`,
      values: age === null ? { count: queued } : { count: queued, age: age.value },
      queued,
      attention: 0,
      announce: false,
    };
  }

  const progress = input.progress ?? null;
  if (progress !== null) {
    return {
      tone: 'syncing',
      glyph: STATUS_GLYPH.syncing,
      messageKey: 'sync.status.syncing',
      // "3 of 12", not a percentage: a percentage of an unknown total is what a spinner
      // already is, and the officer is trying to work out whether to keep walking.
      values: { done: progress.done, total: progress.total },
      queued,
      attention: 0,
      announce: false,
    };
  }

  if (queued > 0) {
    // Reachable, nothing in flight, work still queued. Either the backoff is holding it
    // or the media is deferred to Wi-Fi; either way the honest word is "queued", not
    // "syncing", and the count is what makes it checkable.
    return {
      tone: 'syncing',
      glyph: STATUS_GLYPH.syncing,
      messageKey: 'sync.status.queued',
      values: { count: queued },
      queued,
      attention: 0,
      announce: false,
    };
  }

  return {
    tone: 'synced',
    glyph: STATUS_GLYPH.synced,
    messageKey: 'sync.status.allSynced',
    values: {},
    queued: 0,
    attention: 0,
    announce: true,
  };
}
