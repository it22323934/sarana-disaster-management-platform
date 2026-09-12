/**
 * Storage limits.
 *
 * The failure being prevented: a device fills up, the camera returns a zero-byte file,
 * the form saves happily, and forty assessments turn out to have no photographs. Every
 * branch here has to produce a message.
 */

import { describe, expect, it } from 'vitest';

import {
  MEDIA_CACHE_LIMIT_BYTES,
  REFUSE_FREE_BYTES,
  WARN_FREE_BYTES,
  assessStorage,
  plannedEvictions,
  type EvictionCandidate,
} from './guard.js';

const MB = 1024 * 1024;

describe('assessStorage', () => {
  it('says nothing when there is room', () => {
    const verdict = assessStorage({ freeBytes: 2_000 * MB, mediaCacheBytes: 0 });
    expect(verdict.level).toBe('ok');
    expect(verdict.messageKey).toBeNull();
    expect(verdict.mayCapture).toBe(true);
  });

  it('warns at 200MB free but keeps working', () => {
    const verdict = assessStorage({ freeBytes: WARN_FREE_BYTES - 1, mediaCacheBytes: 0 });
    expect(verdict.level).toBe('low');
    expect(verdict.mayCapture).toBe(true);
    expect(verdict.messageKey).toBe('storage.lowWarning');
    expect(verdict.values.freeMb).toBe(199);
  });

  it('refuses photo capture at 50MB free, with the number in the message', () => {
    // Refusing up front is the whole point. A silent capture failure is discovered days
    // later by someone who no longer has access to the house.
    const verdict = assessStorage({ freeBytes: REFUSE_FREE_BYTES - 1, mediaCacheBytes: 0 });
    expect(verdict.level).toBe('critical');
    expect(verdict.mayCapture).toBe(false);
    expect(verdict.messageKey).toBe('storage.criticalRefusePhoto');
    expect(verdict.values.freeMb).toBe(49);
  });

  it('treats the thresholds as floors, not ranges', () => {
    expect(assessStorage({ freeBytes: WARN_FREE_BYTES, mediaCacheBytes: 0 }).level).toBe('ok');
    expect(assessStorage({ freeBytes: REFUSE_FREE_BYTES, mediaCacheBytes: 0 }).level).toBe('low');
  });
});

function item(id: string, sizeMb: number, status: string, day: number): EvictionCandidate {
  return {
    id,
    size_bytes: sizeMb * MB,
    created_at: `2026-09-${String(day).padStart(2, '0')}T06:00:00.000Z`,
    status,
  };
}

describe('plannedEvictions', () => {
  it('evicts nothing while the cache is under the cap', () => {
    const plan = plannedEvictions([item('a', 100, 'uploaded', 1)], { cacheBytes: 100 * MB });
    expect(plan.evict).toEqual([]);
    expect(plan.stillOver).toBe(false);
  });

  it('evicts uploaded media oldest-first, and only as much as it needs', () => {
    const candidates = [
      item('newest', 200, 'uploaded', 8),
      item('oldest', 200, 'uploaded', 1),
      item('middle', 200, 'uploaded', 4),
    ];
    const plan = plannedEvictions(candidates, { cacheBytes: 600 * MB });
    expect(plan.evict.map((entry) => entry.id)).toEqual(['oldest']);
    expect(plan.reclaimed).toBe(200 * MB);
    expect(plan.stillOver).toBe(false);
  });

  it('never evicts media that has not reached the server', () => {
    // This is the rule the whole function exists for. Deleting an unsynced photo destroys
    // the only copy of evidence attached to a household's damage claim, and no amount of
    // cache pressure justifies it.
    const candidates = [
      item('unsynced-and-old', 400, 'pending', 1),
      item('deferred-and-old', 300, 'deferred', 2),
      item('uploaded', 100, 'uploaded', 9),
    ];
    const plan = plannedEvictions(candidates, { cacheBytes: 800 * MB });
    expect(plan.evict.map((entry) => entry.id)).toEqual(['uploaded']);
    expect(plan.stillOver).toBe(true);
  });

  it('reports that it is still over rather than pretending it fixed it', () => {
    // The honest answer to a full disk is to stop accepting new photos, which
    // assessStorage does. Silently reporting success here would hide that.
    const plan = plannedEvictions([item('a', 10, 'pending', 1)], {
      cacheBytes: MEDIA_CACHE_LIMIT_BYTES + 10 * MB,
    });
    expect(plan.evict).toEqual([]);
    expect(plan.stillOver).toBe(true);
  });
});
