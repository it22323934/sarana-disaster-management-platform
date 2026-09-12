/**
 * Number formatting for a page that will be screenshotted.
 *
 * `@sarana/ts-shared/format` owns money and dates and this file does not duplicate either.
 * What it adds is the handful of derived figures this site publishes — percentages,
 * counts, day spans — and one rule that applies to all of them.
 *
 * **Every number on this site groups the same way in all three languages.**
 *
 * `formatLKR` already pins `en-LK` and the reasoning is written out in that file: Tamil
 * groups in lakhs and crores, so `Intl.NumberFormat('ta-LK')` renders a national total as
 * `1,20,00,00,00,000.00` against `120,000,000,000.00`. Two people reading the same figure
 * off the same screen and saying different numbers aloud is bad in an operations room and
 * worse here, because this page exists to be quoted. A journalist screenshots the Tamil
 * page, a fact-checker opens the English one, and they must be looking at the same number.
 *
 * So the counts and percentages follow money onto `en-LK` rather than following the
 * interface language. Dates do not: a date is read, not compared digit by digit, and
 * `formatDate` renders it in the reader's own calendar conventions.
 */

import { formatLKR, formatLKRCompact, type LKRCents } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

/** The one grouping locale, for the reason in this file's docstring. */
const GROUPING_LOCALE = 'en-LK';

export { formatLKR, formatLKRCompact };
export type { LKRCents };

/** `12,847`. Grouped, never abbreviated: a count of households is not a rounding target. */
export function formatCount(value: number): string {
  return new Intl.NumberFormat(GROUPING_LOCALE).format(value);
}

/**
 * `93.5%` from a 0-1 fraction, or an em dash when the fraction is null.
 *
 * Null is not zero. A district that has disbursed nothing has no confirmation rate, and
 * rendering that as `0.0%` states that everyone who was paid failed to confirm — which is
 * a specific accusation about a district that in fact paid nobody.
 */
export function formatPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return '—';
  return `${new Intl.NumberFormat(GROUPING_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(fraction * 100)}%`;
}

/** A day count, or an em dash. Same null reasoning as `formatPercent`. */
export function formatDays(days: number | null | undefined): string {
  if (days === null || days === undefined || Number.isNaN(days)) return '—';
  return new Intl.NumberFormat(GROUPING_LOCALE, { maximumFractionDigits: 1 }).format(days);
}

/** A rate per thousand, or an em dash. */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return '—';
  return new Intl.NumberFormat(GROUPING_LOCALE, { maximumFractionDigits: 1 }).format(rate);
}

/** Seconds to days, for the grievance stats, which publish an interval in seconds. */
export function secondsToDays(seconds: number | null | undefined): number | null {
  if (seconds === null || seconds === undefined) return null;
  return seconds / 86_400;
}

/**
 * Read a trilingual value, falling back to the code rather than to English.
 *
 * A missing translation is a bug the i18n gate catches at build time, so it should not
 * reach here. If it does, showing `LK-21` is honest and still usable; silently showing the
 * English name to a Tamil reader hides the bug and looks deliberate.
 */
export function localisedName(
  name: Readonly<Record<string, string>> | undefined,
  locale: Locale,
  fallback: string,
): string {
  return name?.[locale] ?? name?.en ?? fallback;
}

/**
 * A district's DS-division code shortened for a table cell, e.g. `LK-21-03` -> `03`.
 *
 * The full code stays in the row's `title` and in every export. A table of thirty rows
 * that repeats `LK-21-` thirty times spends its width on the part that does not vary,
 * which on a cheap phone is the difference between a readable table and a scrolling one.
 */
export function shortDsCode(code: string): string {
  const parts = code.split('-');
  return parts.length >= 4 ? (parts[3] ?? code) : (parts[parts.length - 1] ?? code);
}
