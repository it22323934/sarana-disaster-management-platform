/**
 * Quiet hours, pinned to the Python rule they mirror.
 *
 * `agent_svc.agents.warning.channels` decides what actually happens to a message; this
 * module only shows an operator what is about to. The duplication is worth it for the same
 * reason the SMS segment count is duplicated - the composer has to say, while the message
 * is still being written, that it will be held until 06:00 - and it is worth it only if
 * the two agree.
 *
 * So these tests walk a whole day in Colombo local time and assert every boundary the
 * Python module documents. If they diverge, the Python one is right: it is what actually
 * defers the SMS.
 *
 * The clock is built from UTC instants rather than from local wall-clock parts, because a
 * `Date` constructed from Colombo parts in a browser running on any other timezone is a
 * different instant. Sri Lanka is UTC+5:30, so 22:00 Colombo is 16:30 UTC.
 */

import { describe, expect, it } from 'vitest';

import {
  BYPASS_FROM_CLASS,
  QUIET_END_HOUR,
  QUIET_RELEASE_HOUR,
  QUIET_START_HOUR,
  colomboHour,
  colomboParts,
  inQuietHours,
  quietHoursState,
  releaseAt,
} from './quiet-hours';

/** An instant at a given Colombo wall-clock hour, expressed in UTC. Colombo is +5:30. */
function atColomboHour(hour: number, minute = 0): Date {
  const utcMinutes = hour * 60 + minute - 330;
  const date = new Date(Date.UTC(2025, 10, 28, 0, 0, 0));
  date.setUTCMinutes(date.getUTCMinutes() + utcMinutes);
  return date;
}

describe('the Colombo clock', () => {
  it('reads the hour in Colombo, not in UTC', () => {
    // The whole rule turns on this. A UTC hour test is off by five and a half hours, which
    // puts the entire quiet window in the wrong half of the evening.
    expect(colomboHour(atColomboHour(22))).toBe(22);
    expect(colomboHour(atColomboHour(0))).toBe(0);
    expect(colomboHour(atColomboHour(5))).toBe(5);
  });

  it('reads midnight as hour zero rather than as twenty-four', () => {
    // ICU renders midnight as "24" under some locales, which would put midnight outside a
    // window defined as `hour >= 22 || hour < 5` and silently send at 00:00.
    expect(colomboHour(atColomboHour(0, 1))).toBe(0);
  });
});

describe('the quiet window', () => {
  it('is inclusive of its start hour', () => {
    expect(inQuietHours(atColomboHour(QUIET_START_HOUR, 0))).toBe(true);
    expect(inQuietHours(atColomboHour(QUIET_START_HOUR - 1, 59))).toBe(false);
  });

  it('is exclusive of its end hour', () => {
    // 05:00 is out. A window that included it would hold a message for an hour past the
    // point the rule says people are awake.
    expect(inQuietHours(atColomboHour(QUIET_END_HOUR, 0))).toBe(false);
    expect(inQuietHours(atColomboHour(QUIET_END_HOUR - 1, 59))).toBe(true);
  });

  it('spans midnight', () => {
    // The window wraps, which is why the predicate is an OR rather than a range test.
    expect(inQuietHours(atColomboHour(23, 30))).toBe(true);
    expect(inQuietHours(atColomboHour(0, 30))).toBe(true);
    expect(inQuietHours(atColomboHour(3, 0))).toBe(true);
  });

  it('covers exactly seven hours of the day and no more', () => {
    const quiet = Array.from({ length: 24 }, (_, hour) => hour).filter((hour) =>
      inQuietHours(atColomboHour(hour, 30)),
    );
    expect(quiet).toEqual([0, 1, 2, 3, 4, 22, 23]);
  });
});

describe('what a class 3 alert does at 2am', () => {
  it('sends anyway, because that bypass is the point of writing the rule down', () => {
    const state = quietHoursState(atColomboHour(2), BYPASS_FROM_CLASS);
    expect(state.active).toBe(true);
    expect(state.bypasses).toBe(true);
    expect(state.deferred).toBe(false);
  });

  it('holds a class 2 alert instead, and says when it will go', () => {
    const state = quietHoursState(atColomboHour(2), 2);
    expect(state.deferred).toBe(true);
    expect(colomboHour(state.releaseAt)).toBe(QUIET_RELEASE_HOUR);
  });

  it('treats an unknown severity as not bypassing', () => {
    // A draft whose severity nobody has set must not wake a district on the strength of a
    // missing field. Assuming the highest class is the dangerous default here.
    const state = quietHoursState(atColomboHour(2), null);
    expect(state.bypasses).toBe(false);
    expect(state.deferred).toBe(true);
  });

  it('defers nothing during the day, whatever the class', () => {
    for (const severity of [null, 0, 1, 2, 3, 4]) {
      expect(quietHoursState(atColomboHour(14), severity).deferred).toBe(false);
    }
  });
});

describe('when a deferred message goes out', () => {
  it('is released at 06:00 Colombo exactly, not at 06:30', () => {
    // Not on the minute the window ends: a message arriving at 05:00 still wakes the
    // household that set an alarm for six.
    expect(QUIET_RELEASE_HOUR).toBe(QUIET_END_HOUR + 1);

    // The minute is asserted, not only the hour, because this is where the half-hour
    // offset bit. Snapping to the top of a UTC hour reads as 06:00 to an hour-only
    // assertion and is 06:30 in Colombo.
    for (const hour of [0, 3, 12, 22, 23]) {
      const release = releaseAt(atColomboHour(hour, 17));
      expect(colomboParts(release)).toEqual({ hour: QUIET_RELEASE_HOUR, minute: 0 });
    }
  });

  it('is always in the future', () => {
    for (const hour of [0, 5, 6, 7, 12, 22, 23]) {
      const moment = atColomboHour(hour, 15);
      expect(releaseAt(moment).getTime()).toBeGreaterThan(moment.getTime());
    }
  });

  it('is tomorrow when 06:00 has already passed today', () => {
    const moment = atColomboHour(23);
    const release = releaseAt(moment);
    // Under seven hours away: 23:00 to 06:00 the next morning.
    const hours = (release.getTime() - moment.getTime()) / 3_600_000;
    expect(hours).toBeGreaterThan(6);
    expect(hours).toBeLessThanOrEqual(7);
  });
});
