/**
 * Backoff.
 *
 * The cap is the part that matters to a person: it decides how long an officer who has
 * just walked back into coverage stares at a device that is not syncing.
 */

import { describe, expect, it } from 'vitest';

import { BASE_DELAY_MS, MAX_DELAY_MS, RetrySchedule, delayFor } from './backoff.js';

/** Always the top of the jitter window, so the ceiling itself can be asserted. */
const ceiling = { random: () => 0.999_999 };

describe('delayFor', () => {
  it('does not wait at all before the first attempt', () => {
    expect(delayFor(0, ceiling)).toBe(0);
  });

  it('doubles the ceiling on each attempt', () => {
    expect(delayFor(1, ceiling)).toBe(BASE_DELAY_MS - 1);
    expect(delayFor(2, ceiling)).toBe(2 * BASE_DELAY_MS - 1);
    expect(delayFor(3, ceiling)).toBe(4 * BASE_DELAY_MS - 1);
    expect(delayFor(4, ceiling)).toBe(8 * BASE_DELAY_MS - 1);
  });

  it('never waits longer than five minutes, however many times it has failed', () => {
    // The number an officer experiences. Uncapped, attempt 20 would be a fortnight, and
    // the app would look broken for the rest of the response.
    for (const attempt of [10, 20, 100, 10_000]) {
      expect(delayFor(attempt, ceiling)).toBeLessThanOrEqual(MAX_DELAY_MS);
    }
    expect(delayFor(100, ceiling)).toBe(MAX_DELAY_MS - 1);
  });

  it('does not overflow to Infinity after a day of failures', () => {
    // Repeated doubling reaches Infinity around attempt 1080. A device left on a
    // windowsill in a cut-off division gets there.
    expect(Number.isFinite(delayFor(5_000, ceiling))).toBe(true);
  });

  it('uses full jitter, so devices coming back on one cell tower do not retry together', () => {
    const draws = new Set(
      Array.from({ length: 200 }, (_, index) =>
        delayFor(6, { random: () => index / 200 }),
      ),
    );
    // A small wobble would collapse these into a handful of values.
    expect(draws.size).toBeGreaterThan(150);
    expect(Math.min(...draws)).toBe(0);
  });
});

describe('RetrySchedule', () => {
  it('allows the first run immediately', () => {
    expect(new RetrySchedule(ceiling).mayRun(0)).toBe(true);
  });

  it('holds the next run back after a failure', () => {
    const schedule = new RetrySchedule(ceiling);
    const delay = schedule.fail(10_000);
    expect(delay).toBe(BASE_DELAY_MS - 1);
    expect(schedule.mayRun(10_000)).toBe(false);
    expect(schedule.mayRun(10_000 + delay)).toBe(true);
  });

  it('reports how long the wait has left, for the strip to show', () => {
    const schedule = new RetrySchedule(ceiling);
    schedule.fail(0);
    expect(schedule.waitMs(400)).toBe(BASE_DELAY_MS - 1 - 400);
    expect(schedule.waitMs(999_999)).toBe(0);
  });

  it('resets completely on success', () => {
    // A device that just synced has demonstrated the network is there. Carrying the old
    // backoff forward would punish it for a problem that is over.
    const schedule = new RetrySchedule(ceiling);
    schedule.fail(0);
    schedule.fail(0);
    schedule.fail(0);
    schedule.succeed();
    expect(schedule.attempt).toBe(0);
    expect(schedule.mayRun(0)).toBe(true);
    expect(schedule.fail(0)).toBe(BASE_DELAY_MS - 1);
  });

  it('lets a deliberate refresh through without forgetting how bad the network is', () => {
    // Pull-to-refresh means the user knows something the app cannot detect - they have
    // walked to the top of the hill. Making them wait out a backoff they did not cause is
    // the wrong answer; forgetting the attempt count would also be wrong, because the
    // next automatic retry should still be spaced out.
    const schedule = new RetrySchedule(ceiling);
    schedule.fail(0);
    schedule.fail(0);
    schedule.allowNow();
    expect(schedule.mayRun(0)).toBe(true);
    expect(schedule.attempt).toBe(2);
  });
});
