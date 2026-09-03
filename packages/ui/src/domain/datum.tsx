'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * The data primitives: LKRAmount, ReferenceCode, HashDisplay, RelativeTime.
 *
 * All four are mono with tabular figures, and that is functional rather than stylistic:
 * amounts have to align down a column so a reviewer can see an outlier without reading
 * every row, and a hash has to be scannable character by character by someone comparing
 * it against a printout.
 *
 * All four also render the machine value and the human value together. A reference code
 * with no context, an amount with no currency, a timestamp shown only as "12 minutes ago"
 * - each of those is a figure an operator can act on wrongly, and the second
 * representation is what stops it.
 */

import {
  COLOMBO_TIMEZONE,
  formatDateTime,
  formatLKR,
  formatRelative,
  type LKRCents,
} from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';
import { useEffect, useState, type ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

const DATUM = 'font-mono [font-variant-numeric:tabular-nums]';

export interface LKRAmountProps {
  /** Integer minor units. A float here means one leaked into a money path upstream. */
  readonly cents: LKRCents;
  readonly locale?: Locale;
  /** Drop the `LKR` prefix inside a column already headed with the currency. */
  readonly withCurrency?: boolean;
  /**
   * Reversed, superseded, or otherwise no longer the operative figure.
   *
   * Struck through *and* labelled: a strikethrough is a visual convention that does not
   * reach a screen reader, and "LKR 25,000" read out with no qualification from a
   * reversed entry is a wrong answer to "how much was this household paid".
   */
  readonly voided?: boolean;
  readonly voidedLabel?: string;
  readonly className?: string;
}

export function LKRAmount({
  cents,
  withCurrency = true,
  voided = false,
  voidedLabel,
  className,
}: LKRAmountProps) {
  // `en-LK` grouping in all three locales, which is what `formatLKR` documents: Sinhala
  // and Tamil use the same lakh-free thousands grouping for currency in Sri Lanka, and
  // switching digit shapes per locale would break the column alignment the mono stack
  // exists to provide.
  const formatted = formatLKR(cents, { withCurrency, locale: 'en-LK' });

  return (
    <span
      data-sarana-datum=""
      className={cn(DATUM, voided && 'line-through opacity-70', className)}
    >
      {formatted}
      {voided && voidedLabel ? <span className="sr-only"> ({voidedLabel})</span> : null}
    </span>
  );
}

export interface ReferenceCodeProps {
  /** e.g. `INC-251128-K4M2XA`. The public handle; never the UUID. */
  readonly code: string;
  /** What kind of thing it names, e.g. "Incident". Localised, and always rendered. */
  readonly kind?: ReactNode;
  readonly className?: string;
}

/**
 * A public reference.
 *
 * Codes are the identity; a place name or a description is only ever a label. This is
 * what a citizen reads out on the phone and what an officer writes on a form, so it is
 * rendered at full size and never truncated.
 */
export function ReferenceCode({ code, kind, className }: ReferenceCodeProps) {
  return (
    <span className={cn('inline-flex items-baseline gap-1.5', className)}>
      {kind ? <span className="text-2xs text-[var(--text-muted)]">{kind}</span> : null}
      <span data-sarana-datum="" className={cn(DATUM, 'text-[var(--text-primary)]')}>
        {code}
      </span>
    </span>
  );
}

/** Group a hex digest in fours, so the eye can hold a position while comparing. */
export function groupHash(hash: string, groupSize = 4): string {
  return hash.replace(new RegExp(`(.{${groupSize}})`, 'g'), '$1 ').trim();
}

export interface HashDisplayProps {
  /** The full digest. Always kept whole in the DOM, even when visually truncated. */
  readonly hash: string;
  /** Number of leading characters to show. The rest is available on copy. */
  readonly truncateTo?: number;
  readonly copyLabel: string;
  readonly copiedLabel: string;
  /** Where this digest can be checked. Rendered as a real link, not a tooltip. */
  readonly verifyHref?: string;
  readonly verifyLabel?: string;
  readonly className?: string;
}

export function HashDisplay({
  hash,
  truncateTo = 16,
  copyLabel,
  copiedLabel,
  verifyHref,
  verifyLabel,
  className,
}: HashDisplayProps) {
  const [copied, setCopied] = useState(false);
  const shown = hash.length > truncateTo ? hash.slice(0, truncateTo) : hash;

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy(): Promise<void> {
    // The full digest, never the truncated display value: a partial hash pasted into a
    // verifier is a failed check that looks like a tampered ledger.
    await navigator.clipboard?.writeText(hash);
    setCopied(true);
  }

  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span
        data-sarana-datum=""
        // The whole digest for anyone reading the DOM, copying by selection, or using a
        // screen reader; the truncation is purely visual.
        title={hash}
        className={cn(DATUM, 'text-xs text-[var(--text-primary)]')}
      >
        {groupHash(shown)}
        {hash.length > truncateTo ? <span aria-hidden="true">…</span> : null}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? copiedLabel : copyLabel}
        className={cn(
          'rounded-[var(--radius-cell)] px-1.5 py-0.5 text-2xs',
          'text-[var(--text-muted)] hover:text-[var(--text-primary)]',
          FOCUS_RING,
        )}
      >
        {copied ? copiedLabel : copyLabel}
      </button>
      {verifyHref && verifyLabel ? (
        <a
          href={verifyHref}
          className={cn('text-2xs text-[var(--text-accent)] underline', FOCUS_RING)}
        >
          {verifyLabel}
        </a>
      ) : null}
    </span>
  );
}

export interface RelativeTimeProps {
  /** UTC ISO-8601, as it crosses the wire. */
  readonly value: string | Date;
  readonly locale?: Locale;
  /** Injectable for tests and for Storybook, where "now" has to be deterministic. */
  readonly now?: Date;
  readonly className?: string;
}

/**
 * Relative and absolute, always both.
 *
 * Operators read queues by recency far more than by wall-clock time, so the relative
 * form leads. But a stale "12 minutes ago" on a page that has been open for an hour is a
 * real hazard during an incident, so the Colombo wall-clock time is rendered beside it
 * rather than hidden in a tooltip - a tooltip does not open on the handset a GN officer
 * is holding.
 */
export function RelativeTime({ value, locale = 'en', now, className }: RelativeTimeProps) {
  const date = value instanceof Date ? value : new Date(value);
  const iso = date.toISOString();

  return (
    <span className={cn('inline-flex items-baseline gap-1.5', className)}>
      <time dateTime={iso} className="text-sm text-[var(--text-primary)]">
        {formatRelative(date, locale, now)}
      </time>
      <span
        data-sarana-datum=""
        className={cn(DATUM, 'text-2xs text-[var(--text-muted)]')}
        // The zone is named because a situation report crosses timezones the moment it
        // is forwarded, and "04:30" with no zone has been read as UTC before.
        title={COLOMBO_TIMEZONE}
      >
        {formatDateTime(date, locale)}
      </span>
    </span>
  );
}
