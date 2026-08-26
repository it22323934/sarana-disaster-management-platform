import { describe, expect, it } from 'vitest';

import { formatLKR, formatLKRCompact, rupeesToCents } from './money.js';

describe('formatLKR', () => {
  it('renders minor units as grouped rupees', () => {
    expect(formatLKR(125_000_000)).toBe('LKR 1,250,000.00');
  });

  it('rejects a non-integer, because money is never a float', () => {
    expect(() => formatLKR(12.5)).toThrow(TypeError);
  });

  it('keeps the sign outside the currency marker', () => {
    expect(formatLKR(-50_000)).toBe('LKR -500.00');
  });
});

describe('formatLKRCompact', () => {
  it('renders the Ditwah damage figure the way a dashboard tile would', () => {
    // USD 4.1bn at roughly LKR 300 = LKR 1.23tn; compact tops out at bn.
    expect(formatLKRCompact(123_000_000_000_000)).toBe('LKR 1230.0bn');
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
