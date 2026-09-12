/**
 * LKR formatting.
 *
 * Money crosses the wire as integer minor units and is formatted only here, at the
 * render boundary. Nothing parses these strings back into a number.
 */

/** LKR minor units. 100 = LKR 1.00. */
export type LKRCents = number;

export const CENTS_PER_RUPEE = 100;

/**
 * The one grouping locale money is ever formatted in.
 *
 * Not a parameter, and this is the rule rather than a default. Build file 20: "LKR always
 * displayed the same regardless of locale — a mixed-language operations room needs one
 * unambiguous money format."
 *
 * The option used to exist, documented as safe on the grounds that "Sinhala and Tamil both
 * use the en-LK grouping". **That is false for Tamil.** `Intl.NumberFormat('ta-LK')` groups
 * in lakhs and crores, so the same entitlement renders `LKR 1,25,000.00` to a Tamil reader
 * and `LKR 125,000.00` to an English one — and a national total as `1,20,00,00,00,000.00`
 * against `120,000,000,000.00`. Two people reading the same figure off the same screen and
 * saying different numbers aloud is precisely the failure the rule exists to prevent, and
 * it is worst in the room where it matters most.
 *
 * Nothing was rendering it wrongly - `LKRAmount` pinned `en-LK` on every call - but an
 * option typed as a locale string, with a docstring saying the locales agree, is an
 * invitation. Removing it is what actually holds the rule.
 */
const GROUPING_LOCALE = 'en-LK';

export interface MoneyFormatOptions {
  /** Show the `LKR` prefix. Off inside a column already headed with the currency. */
  readonly withCurrency?: boolean;
  /** Drop the decimal part. Used on dashboards where cents are noise. */
  readonly whole?: boolean;
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

  const { withCurrency = true, whole = false } = options;
  const fractionDigits = whole ? 0 : 2;

  const formatted = new Intl.NumberFormat(GROUPING_LOCALE, {
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
    // Ditwah caused USD 4.1bn of direct damage, roughly LKR 1.2tn. National totals
    // reach the trillion tier, so it is not hypothetical headroom.
    [1e12, 'tn'],
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
