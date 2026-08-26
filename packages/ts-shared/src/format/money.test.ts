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
