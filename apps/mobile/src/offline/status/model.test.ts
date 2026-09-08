/**
 * The status strip.
 *
 * One question: **is my work safe?** Every test here is a state a GN officer can actually
 * be in, and asserts that the strip answers it - a wrong answer is how someone walks away
 * from a device holding a day of assessments believing they are on the server.
 */

import { describe, expect, it } from 'vitest';

import { EMPTY_COUNTS, type LogCounts } from '../log/operation-log.js';
import { EMPTY_MEDIA_COUNTS, describeAge, statusStrip, type StatusInput } from './model.js';
import type { NetworkState } from '../sync/connectivity.js';

const ONLINE: NetworkState = { connected: true, reachable: true, kind: 'wifi', metered: false };
const OFF: NetworkState = { connected: false, reachable: false, kind: 'none', metered: false };
const NOW = Date.UTC(2026, 8, 8, 12, 0, 0);

function input(
  overrides: Omit<Partial<StatusInput>, 'operations'> & { operations?: Partial<LogCounts> } = {},
) {
  const { operations, ...rest } = overrides;
  return {
    network: ONLINE,
    operations: { ...EMPTY_COUNTS, ...operations },
    media: EMPTY_MEDIA_COUNTS,
    lastSyncedAt: NOW - 60_000,
    now: NOW,
    ...rest,
  } satisfies StatusInput;
}

describe('statusStrip', () => {
  it('says everything is safe when it is', () => {
    const strip = statusStrip(input({ operations: { synced: 40 } }));
    expect(strip.tone).toBe('synced');
    expect(strip.messageKey).toBe('sync.status.allSynced');
    expect(strip.glyph).toBe('●');
    expect(strip.queued).toBe(0);
  });

  it('announces the move to safe, so a screen reader user gets told too', () => {
    expect(statusStrip(input({ operations: { synced: 1 } })).announce).toBe(true);
  });

  it('counts progress out of the run total, not the shrinking queue', () => {
    // "3 of 12" becoming "3 of 9" reads as the work disappearing. The engine supplies
    // the denominator because it is the only thing that knows what the run started with.
    const strip = statusStrip(
      input({ operations: { syncing: 9, synced: 3 }, progress: { done: 3, total: 12 } }),
    );
    expect(strip.tone).toBe('syncing');
    expect(strip.messageKey).toBe('sync.status.syncing');
    expect(strip.values).toEqual({ done: 3, total: 12 });
  });

  it('says queued, not syncing, when work is waiting on a backoff', () => {
    // Online, nothing in flight, twelve pending. Calling that "syncing" would be a lie
    // the officer could only catch by watching a number that never moves.
    const strip = statusStrip(input({ operations: { pending: 12 } }));
    expect(strip.messageKey).toBe('sync.status.queued');
    expect(strip.values).toEqual({ count: 12 });
  });

  it('shows the queue and the age of the last sync when offline', () => {
    const strip = statusStrip(
      input({
        network: OFF,
        operations: { pending: 12 },
        lastSyncedAt: NOW - 4 * 3_600_000,
      }),
    );
    expect(strip.tone).toBe('offline');
    expect(strip.glyph).toBe('○');
    expect(strip.messageKey).toBe('sync.status.offline.hours');
    expect(strip.values).toEqual({ count: 12, age: 4 });
  });

  it('has a different sentence for a device that has never synced at all', () => {
    // "Last synced never" is more alarming than "4h ago" and belongs in its own string.
    // This is the device whose officer most needs to be told.
    const strip = statusStrip(input({ network: OFF, operations: { pending: 3 }, lastSyncedAt: null }));
    expect(strip.messageKey).toBe('sync.status.offlineNeverSynced');
    expect(strip.values).toEqual({ count: 3 });
  });

  it('says so plainly when offline with nothing queued', () => {
    const strip = statusStrip(input({ network: OFF, operations: { synced: 20 } }));
    expect(strip.messageKey).toBe('sync.status.offlineClear');
    expect(strip.queued).toBe(0);
  });

  it('puts attention above everything, including being offline', () => {
    // The fix for a conflict is on the device. An officer holding two of them needs to
    // know whether or not there is a signal.
    const strip = statusStrip(
      input({ network: OFF, operations: { conflict: 2, pending: 9 } }),
    );
    expect(strip.tone).toBe('attention');
    expect(strip.glyph).toBe('▲');
    expect(strip.values).toEqual({ count: 2 });
    expect(strip.announce).toBe(true);
  });

  it('counts failed operations and refused media as needing attention too', () => {
    const strip = statusStrip(
      input({
        operations: { conflict: 1, failed: 2 },
        media: { ...EMPTY_MEDIA_COUNTS, failed: 3 },
      }),
    );
    expect(strip.attention).toBe(6);
  });

  it('counts deferred photos as queued, so waiting for Wi-Fi is visible', () => {
    // Otherwise the strip says "all synced" while three photographs sit on the device,
    // and the officer finds out when a reviewer asks where the evidence is.
    const strip = statusStrip(
      input({ operations: { synced: 5 }, media: { ...EMPTY_MEDIA_COUNTS, deferred: 3 } }),
    );
    expect(strip.queued).toBe(3);
    expect(strip.tone).toBe('syncing');
  });

  it('does not announce the counter ticking down', () => {
    // A screen reader talking over an officer for the length of a sync is worse than
    // silence. Only the transitions that change the answer to "is my work safe" speak.
    expect(
      statusStrip(input({ operations: { pending: 5 }, progress: { done: 1, total: 5 } })).announce,
    ).toBe(false);
  });
});

describe('describeAge', () => {
  it('rounds to something a person reads at a glance', () => {
    expect(describeAge(30_000)).toEqual({ key: 'justNow', value: 0 });
    expect(describeAge(9 * 60_000)).toEqual({ key: 'minutes', value: 9 });
    expect(describeAge(4 * 3_600_000)).toEqual({ key: 'hours', value: 4 });
    expect(describeAge(50 * 3_600_000)).toEqual({ key: 'days', value: 2 });
  });
});
