/**
 * LKR formatting.
 *
 * Money crosses the wire as integer minor units and is formatted only here, at the
 * render boundary. Nothing parses these strings back into a number.
 */

/** LKR minor units. 100 = LKR 1.00. */
export type LKRCents = number;

export const CENTS_PER_RUPEE = 100;

export interface MoneyFormatOptions {
  /** Show the `LKR` prefix. Off inside a column already headed with the currency. */
  readonly withCurrency?: boolean;
  /** Drop the decimal part. Used on dashboards where cents are noise. */
  readonly whole?: boolean;
  /** Locale for digit grouping. Sinhala and Tamil both use the en-LK grouping. */
  readonly locale?: string;
}

/**
 * Format minor units for display, e.g. `LKR 1,250,000.00`.
 *
 * Throws on a non-integer: a fractional cent means a float leaked into a money path.
 */
export function formatLKR(cents: LKRCents, options: MoneyFormatOptions = {}): string {
  if (!Number.isInteger(cents)) {
    throw new TypeError(
      `expected LKR minor units as an integer, got ${cents}. ` +
        'Money is never a float - check where this value was produced.',
    );
  }

  const { withCurrency = true, whole = false, locale = 'en-LK' } = options;
  const fractionDigits = whole ? 0 : 2;

  const formatted = new Intl.NumberFormat(locale, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Math.abs(cents) / CENTS_PER_RUPEE);

  const sign = cents < 0 ? '-' : '';
  return withCurrency ? `${sign}LKR ${formatted}` : `${sign}${formatted}`;
}

/**
 * Format a large amount compactly for a dashboard tile, e.g. `LKR 4.1bn`.
 *
 * Only for aggregate figures. Never use it for an individual entitlement or
 * disbursement - a household must always see the exact amount.
 */
export function formatLKRCompact(cents: LKRCents): string {
  const rupees = Math.abs(cents) / CENTS_PER_RUPEE;
  const sign = cents < 0 ? '-' : '';

  const units: ReadonlyArray<readonly [number, string]> = [
    [1e9, 'bn'],
    [1e6, 'mn'],
    [1e3, 'k'],
  ];

  for (const [threshold, suffix] of units) {
    if (rupees >= threshold) {
      const scaled = rupees / threshold;
      const digits = scaled >= 100 ? 0 : 1;
      return `${sign}LKR ${scaled.toFixed(digits)}${suffix}`;
    }
  }
  return formatLKR(cents);
}

/** Parse a user-entered rupee amount into minor units, rounding half up. */
export function rupeesToCents(input: string | number): LKRCents {
  const text = typeof input === 'number' ? input.toString() : input.trim().replace(/,/g, '');
  if (!/^-?\d+(\.\d{1,2})?$/.test(text)) {
    throw new TypeError(`not a valid rupee amount: ${input}`);
  }
  const [whole, fraction = ''] = text.split('.');
  const negative = (whole ?? '').startsWith('-');
  const wholeCents = Math.abs(Number.parseInt(whole ?? '0', 10)) * CENTS_PER_RUPEE;
  const fractionCents = Number.parseInt(fraction.padEnd(2, '0'), 10) || 0;
  const total = wholeCents + fractionCents;
  return negative ? -total : total;
}
