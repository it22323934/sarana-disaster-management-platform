/**
 * The components that stop this site asserting more than it knows.
 *
 * `ReadFailure` is the important one. Every page fetches from a service that can be down,
 * and the shape of the failure decides what a reader concludes. A page that renders
 * `Rs. 0` when a service times out has not degraded gracefully — it has published a
 * specific, false and damaging claim about a district that may have disbursed a great
 * deal. So a failed read renders as a named failure with a reason, in the space the figure
 * would have occupied, and never as a number.
 *
 * `AsOf` is the second. A figure with no timestamp on a page that regenerates every five
 * minutes looks live and may be five minutes old — which is fine, and only fine because
 * the page says so.
 */

import type { ReactNode } from 'react';

import { formatDateTime } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';

import type { FailureReason } from '../lib/public-api';

export interface ReadFailureProps {
  readonly reason: FailureReason;
  readonly title: string;
  readonly explanation: string;
  readonly whatToDo: string;
  readonly neverZero: string;
}

/**
 * A figure that could not be read, in the space the figure would have taken.
 *
 * `role="status"` rather than `role="alert"`: a service being briefly unavailable is
 * information, not an emergency, and an assertive region would interrupt a screen reader
 * mid-sentence on a page that may carry several of these.
 *
 * The border is `--pending`, the platform's "a human must act" colour, and not a severity
 * red. Severity on this platform means hazard, and an unreachable service is not a hazard —
 * spending the hazard colour on infrastructure noise is how the ramp stops meaning
 * anything.
 */
export function ReadFailure({
  reason,
  title,
  explanation,
  whatToDo,
  neverZero,
}: ReadFailureProps) {
  return (
    <div
      role="status"
      data-sarana-read-failure={reason}
      className="rounded-[var(--radius-default)] border border-[var(--pending)] bg-[var(--surface-card)] p-4"
    >
      <p className="m-0 font-medium text-[var(--text-primary)]">{title}</p>
      <p className="mt-1 max-w-prose text-sm text-[var(--text-muted)]">{explanation}</p>
      <p className="mt-2 max-w-prose text-xs text-[var(--text-muted)]">{whatToDo}</p>
      <p className="mt-1 max-w-prose text-xs font-medium text-[var(--text-primary)]">
        {neverZero}
      </p>
    </div>
  );
}

/** When a figure was computed, in Colombo time, said out loud rather than implied. */
export function AsOf({
  when,
  locale,
  label,
  className,
}: {
  readonly when: string;
  readonly locale: Locale;
  /** Already interpolated, e.g. "As of 8 Sep 2026, 14:05". */
  readonly label: (formatted: string) => string;
  readonly className?: string;
}) {
  return (
    <p className={className ?? 'mt-4 text-xs text-[var(--text-muted)]'}>
      <time dateTime={when}>{label(formatDateTime(when, locale))}</time>
    </p>
  );
}

/**
 * A figure with its denominator, its provenance and — where it applies — its bad news.
 *
 * Not `StatCard` from the design system, and the reason is the JavaScript budget. That
 * component is in a `'use client'` module because its neighbours in the same file take
 * function props; importing it here would pull the client boundary, React DOM and the
 * button primitive into `/`, which is the one route the brief holds to 120 KB and the one
 * that has to render with scripting off. This is the same card as a server component.
 *
 * `value` is pre-formatted by the caller at the render boundary, exactly as `StatCard`
 * requires, so money never reaches a component as a number.
 */
export function Figure({
  label,
  value,
  context,
  emphasis = 'normal',
  href,
  footer,
}: {
  readonly label: ReactNode;
  readonly value: ReactNode;
  readonly context?: ReactNode;
  /**
   * `normal` for the headline four, `quiet` for a supporting count.
   *
   * There is deliberately no `warning` variant. The brief is explicit that the
   * uncomfortable figures sit next to the good ones "in the same type size", and a
   * variant that made them smaller or greyer would be used on exactly those.
   */
  readonly emphasis?: 'normal' | 'quiet';
  readonly href?: string;
  readonly footer?: ReactNode;
}) {
  const body = (
    <>
      <span className="text-2xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </span>
      <span
        data-sarana-datum=""
        className={
          emphasis === 'quiet'
            ? 'text-lg font-semibold leading-none text-[var(--text-primary)]'
            : 'text-2xl font-semibold leading-none text-[var(--text-primary)]'
        }
      >
        {value}
      </span>
      {context ? <span className="text-xs text-[var(--text-muted)]">{context}</span> : null}
      {footer ? <span className="mt-1 text-2xs text-[var(--text-muted)]">{footer}</span> : null}
    </>
  );

  const className =
    'flex flex-col gap-1 rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4';

  // Every number on the overview links to the breakdown behind it: "nothing is a number
  // without provenance". The whole card is the target rather than the label, because on a
  // handset a 13px label is not a touch target.
  return href ? (
    <a href={href} className={`${className} no-underline hover:bg-[var(--surface-raised)]`}>
      {body}
    </a>
  ) : (
    <div className={className}>{body}</div>
  );
}

/**
 * A table that scrolls sideways inside its own box rather than pushing the page wide.
 *
 * Every table on this site has more columns than a 390px phone can show. Without this the
 * body scrolls horizontally, which on a touch device makes vertical scrolling unreliable
 * and is what the overflow gate in `e2e/layout.spec.ts` fails on.
 *
 * **`tabIndex` and the label are not decoration; axe failed without them.** A container
 * that scrolls with a finger or a trackpad cannot be scrolled with a keyboard unless it can
 * hold focus, so a keyboard-only reader could see the first four columns of the ledger and
 * had no way to reach the fifth. That is `scrollable-region-focusable`, and it fired on
 * `/ta/ledger` before `/en/ledger` — Tamil is wider, so the table overflowed in one
 * language and not the other, which is exactly the failure a single-locale sweep misses.
 *
 * `label` is required rather than optional because a focusable region with no accessible
 * name is announced as an unlabelled group, which trades one violation for another. The
 * design system's `Pagination` requires a label for the same reason.
 */
export function ScrollableTable({
  label,
  children,
}: {
  readonly label: string;
  readonly children: ReactNode;
}) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="w-full overflow-x-auto rounded-[var(--radius-default)] border border-[var(--divider)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
    >
      {children}
    </div>
  );
}

/**
 * A hex digest, grouped in fours, truncated visually and whole in the DOM.
 *
 * The design system's `HashDisplay` does this with a copy button, which makes it a client
 * component with two required label props. On this site the ledger is one of the three
 * routes that must render with scripting off, and a copy button is the only thing that
 * would put React into it — so the grouping is reimplemented here as four lines of server
 * component rather than imported.
 *
 * **The full digest is in `title` and in the text a selection copies.** A truncated hash
 * pasted into a verifier is a failed check that looks like a tampered ledger, so what the
 * eye sees is shortened and what the clipboard gets is not: the `<code>` holds the whole
 * value and the ellipsis is `aria-hidden` decoration over an `overflow` clip.
 */
export function Hash({ value, showChars = 16 }: { readonly value: string; readonly showChars?: number }) {
  const grouped = value.replace(/(.{4})/g, '$1 ').trim();
  return (
    <code
      data-sarana-datum=""
      title={value}
      // `ch` units so the clip lands on a character boundary rather than mid-glyph. The
      // grouping adds one space per four characters, hence the multiplier.
      style={{ maxWidth: `${Math.round(showChars * 1.25)}ch` }}
      className="inline-block overflow-hidden text-ellipsis whitespace-nowrap align-bottom font-mono text-2xs text-[var(--text-primary)]"
    >
      {grouped}
    </code>
  );
}
