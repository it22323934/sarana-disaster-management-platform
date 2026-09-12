/**
 * Colombo date and time formatting.
 *
 * This module had no tests until the design system started rendering every timestamp
 * through it, which is how the `en-LK` ordering bug below went unnoticed: the docstring
 * said `28 Nov 2025` and the function returned `Nov 28, 2025`.
 */

import { describe, expect, it } from 'vitest';

import {
  COLOMBO_TIMEZONE,
  formatDate,
  formatDateTime,
  formatDisasterRelative,
  formatRelative,
  formatTime,
} from './datetime.js';

// 28 Nov 2025, 03:48 in Colombo. Cyclone Ditwah's landfall window.
const INSTANT = '2025-11-27T22:18:00Z';

describe('formatDate', () => {
  it('writes the day before the month in English', () => {
    // CLDR gives `en-LK` the US order, so this returned `Nov 28, 2025` until the tag was
    // changed to `en-GB`. Every situation report and press release in Sri Lanka is
    // day-first, and a date that reads the other way round is misread, not just ugly.
    expect(formatDate(INSTANT, 'en')).toBe('28 Nov 2025');
  });

  it('renders in Colombo local time, not UTC', () => {
    // 22:18 UTC is already the next day in Colombo. A platform that rendered UTC would
    // date an overnight evacuation order to the day before it was issued.
    expect(formatDate(INSTANT, 'en')).toContain('28');
  });

  it('formats in all three locales without throwing', () => {
    for (const locale of ['si', 'ta', 'en'] as const) {
      expect(formatDate(INSTANT, locale).length).toBeGreaterThan(0);
    }
  });
});

describe('formatTime', () => {
  it('is 24-hour, because a runbook never says 3:48 pm', () => {
    expect(formatTime(INSTANT, 'en')).toBe('03:48');
  });

  it('applies the +5:30 offset rather than a whole number of hours', () => {
    // Sri Lanka is UTC+5:30. Anything doing timezone maths in application code gets this
    // wrong by half an hour, which is why only Intl is allowed to do it.
    expect(formatTime('2025-11-27T18:30:00Z', 'en')).toBe('00:00');
  });
});

describe('formatDateTime', () => {
  it('joins the date and the time with a comma', () => {
    expect(formatDateTime(INSTANT, 'en')).toBe('28 Nov 2025, 03:48');
  });
});

describe('formatRelative', () => {
  const now = new Date('2025-11-27T23:00:00Z');

  it('reads backwards for a past instant', () => {
    expect(formatRelative(INSTANT, 'en', now)).toContain('42');
  });

  it('reads forwards for a future instant', () => {
    expect(formatRelative('2025-11-28T02:00:00Z', 'en', now)).toContain('3');
  });
});

describe('formatDisasterRelative', () => {
  const landfall = '2025-11-28T00:00:00Z';

  it('renders whole days as days and whole hours as hours', () => {
    // Runbooks and situation reports are written in these terms, so the units have to
    // match how people say them out loud.
    expect(formatDisasterRelative('2025-11-25T00:00:00Z', landfall)).toBe('T-3d');
    expect(formatDisasterRelative('2025-11-28T06:00:00Z', landfall)).toBe('T+6h');
    expect(formatDisasterRelative(landfall, landfall)).toBe('T+0');
  });

  it('falls back to minutes for anything that is not a whole hour', () => {
    expect(formatDisasterRelative('2025-11-28T00:20:00Z', landfall)).toBe('T+20m');
  });
});

describe('the timezone constant', () => {
  it('is the IANA name, so Intl resolves the half-hour offset from the database', () => {
    expect(COLOMBO_TIMEZONE).toBe('Asia/Colombo');
  });
});
