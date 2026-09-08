/**
 * Formatting on a page that will be screenshotted and quoted.
 *
 * Two properties are asserted here and both are about what a reader concludes rather than
 * about the code being tidy.
 *
 * **Every number groups identically in all three languages.** `formatLKR` already pins
 * `en-LK` and `packages/ts-shared` tests that; what is tested here is that the derived
 * figures this app adds — percentages, counts, day spans — did not quietly follow the
 * interface locale instead. A journalist screenshotting the Tamil page and a fact-checker
 * opening the English one must be looking at the same digits.
 *
 * **Null is never rendered as zero.** A district that disbursed nothing has no confirmation
 * rate, and `0.0%` states that everyone who was paid failed to confirm — a specific
 * accusation about a district that in fact paid nobody.
 */

import { describe, expect, it } from 'vitest';

import {
  formatCount,
  formatDays,
  formatLKR,
  formatPercent,
  formatRate,
  localisedName,
  secondsToDays,
  shortDsCode,
} from './format';

describe('numbers group the same way in every language', () => {
  it('formats a national total in Latin grouping, not lakhs and crores', () => {
    // `Intl.NumberFormat('ta-LK')` would render this as 1,20,00,00,00,000.00. Two people
    // reading the same figure off the same screen and saying different numbers aloud is
    // the failure the rule exists to prevent.
    expect(formatLKR(418234000000, { whole: true })).toBe('LKR 4,182,340,000');
  });

  it('groups a household count', () => {
    expect(formatCount(12847)).toBe('12,847');
  });

  it('formats a fraction as a percentage to one decimal', () => {
    expect(formatPercent(0.935)).toBe('93.5%');
  });
});

describe('null is an absence, never a zero', () => {
  it('renders a missing percentage as an em dash', () => {
    expect(formatPercent(null)).toBe('—');
    expect(formatPercent(undefined)).toBe('—');
  });

  it('renders a missing day count as an em dash', () => {
    expect(formatDays(null)).toBe('—');
  });

  it('renders a missing rate as an em dash', () => {
    expect(formatRate(null)).toBe('—');
  });

  it('still renders a measured zero as zero', () => {
    // The distinction the whole rule rests on: a district that paid everyone and had none
    // confirm is a real 0%, and it must not be hidden behind the same dash as "no data".
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatDays(0)).toBe('0');
    expect(formatCount(0)).toBe('0');
  });

  it('does not turn NaN into a number', () => {
    expect(formatPercent(Number.NaN)).toBe('—');
    expect(formatDays(Number.NaN)).toBe('—');
  });
});

describe('secondsToDays', () => {
  it('converts a week', () => {
    expect(secondsToDays(604800)).toBe(7);
  });

  it('passes null through rather than producing zero days', () => {
    expect(secondsToDays(null)).toBeNull();
  });
});

describe('localisedName', () => {
  const name = { en: 'Kandy', si: 'මහනුවර', ta: 'கண்டி' };

  it('reads the requested locale', () => {
    expect(localisedName(name, 'ta', 'LK-21')).toBe('கண்டி');
  });

  it('falls back to the code, not to English, when the name is missing entirely', () => {
    // Showing `LK-21` is honest and usable. Silently showing an English name to a Tamil
    // reader hides the bug and looks deliberate.
    expect(localisedName(undefined, 'ta', 'LK-21')).toBe('LK-21');
  });
});

describe('shortDsCode', () => {
  it('shortens a DS code to its last segment', () => {
    expect(shortDsCode('LK-21-03')).toBe('03');
  });

  it('shortens a GN code to its last segment', () => {
    expect(shortDsCode('LK-21-03-014')).toBe('014');
  });

  it('leaves an unexpected shape alone rather than mangling it', () => {
    expect(shortDsCode('LK')).toBe('LK');
  });
});
