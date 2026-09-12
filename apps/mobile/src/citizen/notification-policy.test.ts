/**
 * What is allowed to make a handset make a noise.
 *
 * The rule with no exceptions: **an evacuation order is not a notification preference.**
 * Someone who turned off flood watches in June is not thereby someone who declined an
 * evacuation order in November.
 */

import { describe, expect, it } from 'vitest';

import {
  DEFAULT_PREFERENCES,
  HIGHEST_MUTABLE_CLASS,
  decideNotification,
  type NotificationPreferences,
} from './notification-policy.js';

/** 14:00 Colombo. Well outside quiet hours in either direction. */
const DAYTIME = new Date('2026-09-08T08:30:00Z');
/** 02:00 Colombo. */
const NIGHT = new Date('2026-09-07T20:30:00Z');

const MUTED_EVERYTHING: NotificationPreferences = {
  minimumAlertClass: 5,
  aidUpdates: false,
  reportUpdates: false,
};

describe('alerts at class 3 and above', () => {
  it('delivers with every alert muted', () => {
    const decision = decideNotification({
      kind: 'alert',
      impactClass: 3,
      at: DAYTIME,
      preferences: MUTED_EVERYTHING,
    });
    expect(decision).toMatchObject({ deliver: 'now', bypassedMute: true });
  });

  it('delivers at 2am, with everything muted, at the evacuate line', () => {
    // Class 4 is the evacuate line. This is the case the whole module exists for.
    const decision = decideNotification({
      kind: 'alert',
      impactClass: 4,
      at: NIGHT,
      preferences: MUTED_EVERYTHING,
    });
    expect(decision).toMatchObject({
      deliver: 'now',
      bypassedMute: true,
      bypassedQuietHours: true,
    });
  });

  it('does not report a bypass it did not need', () => {
    const decision = decideNotification({
      kind: 'alert',
      impactClass: 3,
      at: DAYTIME,
      preferences: DEFAULT_PREFERENCES,
    });
    expect(decision).toMatchObject({ bypassedMute: false, bypassedQuietHours: false });
  });
});

describe('alerts below class 3', () => {
  it('respects a mute', () => {
    expect(
      decideNotification({
        kind: 'alert',
        impactClass: 2,
        at: DAYTIME,
        preferences: { ...DEFAULT_PREFERENCES, minimumAlertClass: 3 },
      }),
    ).toEqual({ deliver: 'never', reason: 'muted-by-preference' });
  });

  it('defers to 06:00 Colombo during quiet hours', () => {
    // A watch-level alert at 2am wakes a district for something that will still be true
    // at six.
    const decision = decideNotification({
      kind: 'alert',
      impactClass: 2,
      at: NIGHT,
      preferences: DEFAULT_PREFERENCES,
    });
    if (decision.deliver !== 'deferred') throw new Error('expected a deferral');
    expect(decision.reason).toBe('quiet-hours');
    // 20:30 UTC is 02:00 Colombo; 06:00 Colombo is 00:30 UTC.
    expect(decision.until.toISOString()).toBe('2026-09-08T00:30:00.000Z');
  });

  it('delivers during the day', () => {
    expect(
      decideNotification({
        kind: 'alert',
        impactClass: 1,
        at: DAYTIME,
        preferences: DEFAULT_PREFERENCES,
      }).deliver,
    ).toBe('now');
  });

  it('treats an alert with no class as class zero, not as an emergency', () => {
    // Assuming the highest class for a message whose grade nobody set would wake a
    // district on the strength of a missing field.
    expect(
      decideNotification({
        kind: 'alert',
        impactClass: null,
        at: NIGHT,
        preferences: { ...DEFAULT_PREFERENCES, minimumAlertClass: 1 },
      }),
    ).toEqual({ deliver: 'never', reason: 'muted-by-preference' });
  });
});

describe('everything that is not an alert', () => {
  it('is fully the user’s call', () => {
    expect(
      decideNotification({
        kind: 'disbursement-released',
        impactClass: null,
        at: DAYTIME,
        preferences: { ...DEFAULT_PREFERENCES, aidUpdates: false },
      }),
    ).toEqual({ deliver: 'never', reason: 'muted-by-preference' });
  });

  it('respects quiet hours without exception', () => {
    // A disbursement release at 2am is good news that keeps until morning. None of these
    // is ever life-safety.
    expect(
      decideNotification({
        kind: 'grievance-updated',
        impactClass: null,
        at: NIGHT,
        preferences: DEFAULT_PREFERENCES,
      }).deliver,
    ).toBe('deferred');
  });

  it('separates report updates from money updates', () => {
    const preferences = { ...DEFAULT_PREFERENCES, reportUpdates: false, aidUpdates: true };
    expect(
      decideNotification({ kind: 'report-status', impactClass: null, at: DAYTIME, preferences })
        .deliver,
    ).toBe('never');
    expect(
      decideNotification({
        kind: 'disbursement-released',
        impactClass: null,
        at: DAYTIME,
        preferences,
      }).deliver,
    ).toBe('now');
  });
});

describe('the settings ceiling', () => {
  it('stops the mute control where the rule stops', () => {
    // The settings screen shows the control ending at 2, with an explanation, rather than
    // accepting a value it will then ignore.
    expect(HIGHEST_MUTABLE_CLASS).toBe(2);
  });
});
