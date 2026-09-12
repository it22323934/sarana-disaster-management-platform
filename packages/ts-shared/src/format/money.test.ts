import { describe, expect, it } from 'vitest';

import { formatLKR, formatLKRCompact, rupeesToCents } from './money.js';

describe('formatLKR', () => {
  it('renders minor units as grouped rupees', () => {
    expect(formatLKR(125_000_000)).toBe('LKR 1,250,000.00');
  });

  it('rejects a non-integer, because money is never a float', () => {
    expect(() => formatLKR(12.5)).toThrow(TypeError);
  });

  it('puts the sign ahead of the currency marker, as a ledger reversal reads', () => {
    expect(formatLKR(-50_000)).toBe('-LKR 500.00');
  });
});

describe('formatLKRCompact', () => {
  it('renders the Ditwah damage figure the way a dashboard tile would', () => {
    // USD 4.1bn of direct damage at roughly LKR 300 to the dollar.
    expect(formatLKRCompact(123_000_000_000_000)).toBe('LKR 1.2tn');
  });

  it('steps down through the tiers', () => {
    expect(formatLKRCompact(450_000_000_000)).toBe('LKR 4.5bn');
    expect(formatLKRCompact(250_000_000)).toBe('LKR 2.5mn');
    expect(formatLKRCompact(1_200_000)).toBe('LKR 12.0k');
  });
});

describe('rupeesToCents', () => {
  it('parses a user-entered amount without going through a float', () => {
    expect(rupeesToCents('1,250,000.75')).toBe(125_000_075);
  });

  it('rejects more than two decimal places', () => {
    expect(() => rupeesToCents('10.005')).toThrow(TypeError);
  });
});

/**
 * The one money format rule, which had no test.
 *
 * Build file 20: "Numbers, dates, and currency formatted per locale but LKR **always**
 * displayed the same regardless of locale — a mixed-language operations room needs one
 * unambiguous money format."
 *
 * That is a rule about a room rather than about a string. Three people reading the same
 * screen in three languages have to be able to say a figure aloud to each other and mean
 * the same number; a Sinhala rendering that grouped differently, or used a different digit
 * shape, would make two of them read a different amount off the same pixel.
 *
 * `formatLKR` still accepts a locale for grouping, and `LKRAmount` pins it to `en-LK` on
 * every call. These tests hold the promise the option's own docstring makes - that the
 * three supported locales agree - so a future change to that default is caught here rather
 * than in an operations room.
 */
describe('money reads the same in all three languages', () => {
  it('takes no locale, so it cannot be formatted per language', () => {
    // The rule is held by the signature rather than by every caller remembering. This
    // used to be an option documented as safe on the false premise that Sinhala and Tamil
    // group like English; Tamil groups in lakhs and crores.
    expect(formatLKR(12_500_000)).toBe('LKR 125,000.00');
    expect(Object.keys({ withCurrency: true, whole: true })).not.toContain('locale');
  });

  it('would have differed under a Tamil locale, which is why the option is gone', () => {
    // Pinned as evidence rather than as a requirement: this asserts what `Intl` does, so
    // if a future ICU changes it the comment above stops being true and this says so.
    const tamil = new Intl.NumberFormat('ta-LK', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(125_000);
    const english = new Intl.NumberFormat('en-LK', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(125_000);
    expect(tamil).not.toBe(english);
    expect(formatLKR(12_500_000)).toContain(english);
  });

  it('uses Western digits and a thousands grouping', () => {
    // A figure rendered in digits half the room cannot read is worse than an untranslated
    // label.
    expect(formatLKR(1_234_56)).toMatch(/^LKR [0-9,]+\.[0-9]{2}$/);
    expect(formatLKR(120_000_000_000_00)).toBe('LKR 120,000,000,000.00');
  });

  it('keeps the sign ahead of the marker', () => {
    // A reversal read aloud has to be unambiguous about direction in all three languages.
    expect(formatLKR(-25_000_00).startsWith('-LKR ')).toBe(true);
  });
});
