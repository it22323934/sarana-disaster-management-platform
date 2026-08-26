/**
 * Colombo date and time formatting.
 *
 * Everything crosses the wire as UTC ISO-8601 and is rendered in Asia/Colombo here.
 * Timezone maths never happens in application code - `Intl` does it against the IANA
 * database, which is the only thing that knows Sri Lanka is UTC+5:30 and not +5:00.
 */

import type { Locale } from '../i18n/types.js';

export const COLOMBO_TIMEZONE = 'Asia/Colombo';

/** Intl locale tags for the three SARANA locales. */
const INTL_LOCALES: Record<Locale, string> = {
  si: 'si-LK',
  ta: 'ta-LK',
  en: 'en-LK',
};

function toDate(value: Date | string | number): Date {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new TypeError(`not a valid instant: ${String(value)}`);
  }
  return date;
}

/** `28 Nov 2025` in Colombo local time. */
export function formatDate(value: Date | string | number, locale: Locale = 'en'): string {
  return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
    timeZone: COLOMBO_TIMEZONE,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(toDate(value));
}

/** `04:30` in Colombo local time, 24-hour. */
export function formatTime(value: Date | string | number, locale: Locale = 'en'): string {
  return new Intl.DateTimeFormat(INTL_LOCALES[locale], {
    timeZone: COLOMBO_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(toDate(value));
}

/** `28 Nov 2025, 04:30` in Colombo local time. */
export function formatDateTime(value: Date | string | number, locale: Locale = 'en'): string {
  return `${formatDate(value, locale)}, ${formatTime(value, locale)}`;
}

/**
 * `12 minutes ago`, `in 3 hours`.
 *
 * Operators read incident lists by recency far more than by wall-clock time, so this is
 * the default in list views. The absolute time always appears alongside it in a tooltip
 * or a detail pane - never as the only representation, because a stale relative label on
 * a re-rendered page is a real hazard during an incident.
 */
export function formatRelative(
  value: Date | string | number,
  locale: Locale = 'en',
  now: Date = new Date(),
): string {
  const target = toDate(value);
  const deltaSeconds = Math.round((target.getTime() - now.getTime()) / 1000);

  const formatter = new Intl.RelativeTimeFormat(INTL_LOCALES[locale], { numeric: 'auto' });
  const divisions: ReadonlyArray<readonly [number, Intl.RelativeTimeFormatUnit]> = [
    [60, 'second'],
    [3600, 'minute'],
    [86_400, 'hour'],
    [604_800, 'day'],
    [2_629_800, 'week'],
    [31_557_600, 'month'],
  ];

  let magnitude = Math.abs(deltaSeconds);
  let previous = 1;
  for (const [limit, unit] of divisions) {
    if (magnitude < limit) {
      return formatter.format(Math.round(deltaSeconds / previous), unit);
    }
    previous = limit;
    magnitude = Math.abs(deltaSeconds);
  }
  return formatter.format(Math.round(deltaSeconds / 31_557_600), 'year');
}

/**
 * Render an instant as an offset from landfall, e.g. `T-72h` or `T+14d`.
 *
 * Disaster timelines are spoken in these terms in every runbook and every situation
 * report, so operator surfaces show both this and the wall-clock time.
 */
export function formatDisasterRelative(
  value: Date | string | number,
  landfall: Date | string | number,
): string {
  const deltaSeconds = Math.round(
    (toDate(value).getTime() - toDate(landfall).getTime()) / 1000,
  );
  if (deltaSeconds === 0) return 'T+0';

  const sign = deltaSeconds < 0 ? '-' : '+';
  const magnitude = Math.abs(deltaSeconds);

  if (magnitude % 86_400 === 0) return `T${sign}${magnitude / 86_400}d`;
  if (magnitude % 3600 === 0) return `T${sign}${magnitude / 3600}h`;
  return `T${sign}${Math.floor(magnitude / 60)}m`;
}
