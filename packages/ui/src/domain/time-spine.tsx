'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * TimeSpine - the signature structural element.
 *
 * Everything in SARANA is anchored to a disaster clock, so the spine is a persistent rail
 * across the top of every operational surface showing where the present sits between
 * forecast and recovery, with the milestones that have actually happened plotted on it.
 *
 * It earns its place by encoding something true: order and elapsed time carry real
 * meaning here. A forecast issued after the alert went out is a different situation from
 * one issued before it, and that is legible on a rail and invisible in a list sorted by
 * recency. That is the test every structural device in this system has to pass - if a
 * rail or a divider or a number does not encode information the reader needs, it is
 * deleted.
 *
 * Absolute Colombo time and relative disaster time are shown together, always. "T+6h" is
 * how a runbook is written and how an operator speaks; "28 Nov, 10:30" is what a
 * situation report has to say when it is forwarded across a timezone.
 */

import { formatDateTime, formatDisasterRelative } from '@sarana/ts-shared/format';
import type { Locale } from '@sarana/ts-shared/i18n';
import type { ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';

export interface SpineMilestone {
  readonly id: string;
  /** UTC ISO-8601. */
  readonly at: string;
  readonly label: ReactNode;
  /**
   * Marks a milestone that has not happened yet - a forecast landfall, a scheduled
   * disbursement window. Rendered hollow, so a projection is never read as a fact.
   */
  readonly projected?: boolean;
}

export interface TimeSpineProps {
  /** T+0. The event everything is measured against. UTC ISO-8601. */
  readonly landfall: string;
  /** Where "now" sits. Injectable so a replay and a story are deterministic. */
  readonly now: string;
  /** Left edge of the rail. Defaults to 72 hours before landfall. */
  readonly from?: string;
  /** Right edge. Defaults to 14 days after landfall. */
  readonly to?: string;
  readonly milestones?: readonly SpineMilestone[];
  readonly locale?: Locale;
  /** Names the region, e.g. "Cyclone Ditwah timeline". Localised by the caller. */
  readonly label: string;
  /** "You are here", localised. Read out with the current position. */
  readonly nowLabel: string;
  /** Collapses to a single line: `T+11d - Recovery`. The mobile and compact form. */
  readonly compact?: boolean;
  /** The phase name for the compact form, e.g. "Recovery". Localised. */
  readonly phaseLabel?: string;
  readonly className?: string;
}

const HOUR_MS = 3_600_000;

/** Where an instant sits on the rail, as a 0-100 percentage, clamped to the ends. */
function positionOf(at: number, from: number, to: number): number {
  if (to <= from) return 0;
  const raw = ((at - from) / (to - from)) * 100;
  return Math.min(100, Math.max(0, raw));
}

export function TimeSpine({
  landfall,
  now,
  from,
  to,
  milestones = [],
  locale = 'en',
  label,
  nowLabel,
  compact = false,
  phaseLabel,
  className,
}: TimeSpineProps) {
  const landfallMs = new Date(landfall).getTime();
  const nowMs = new Date(now).getTime();
  const fromMs = from ? new Date(from).getTime() : landfallMs - 72 * HOUR_MS;
  const toMs = to ? new Date(to).getTime() : landfallMs + 14 * 24 * HOUR_MS;

  const nowRelative = formatDisasterRelative(now, landfall);

  if (compact) {
    return (
      <div
        aria-label={label}
        className={cn(
          'flex items-baseline gap-2 border-b border-[var(--divider)] px-4 py-2',
          className,
        )}
      >
        <span data-sarana-datum="" className="font-mono text-sm font-medium text-[var(--text-primary)]">
          {nowRelative}
        </span>
        {phaseLabel ? (
          <span className="text-xs text-[var(--text-muted)]">{phaseLabel}</span>
        ) : null}
        <span
          data-sarana-datum=""
          className="ml-auto font-mono text-2xs text-[var(--text-muted)]"
        >
          {formatDateTime(now, locale)}
        </span>
      </div>
    );
  }

  const nowPosition = positionOf(nowMs, fromMs, toMs);
  const landfallPosition = positionOf(landfallMs, fromMs, toMs);

  return (
    <section
      aria-label={label}
      className={cn(
        'border-b border-[var(--divider)] bg-[var(--surface-base)] px-6 pb-6 pt-4',
        className,
      )}
    >
      {/* The whole rail restated as text, for anyone who cannot read a graphic. It is
          not a summary - it is the same facts, which is what makes the visual optional. */}
      <p className="sr-only">
        {nowLabel}: {nowRelative}, {formatDateTime(now, locale)}.{' '}
        {milestones
          .map(
            (milestone) =>
              `${formatDisasterRelative(milestone.at, landfall)} ${
                typeof milestone.label === 'string' ? milestone.label : ''
              }`,
          )
          .join('. ')}
      </p>

      <div aria-hidden="true" className="relative h-16">
        <div className="absolute inset-x-0 top-8 h-px bg-[var(--divider)]" />

        {/* Landfall. The only marker drawn as a band rather than a tick: T+0 is a moment
            the whole timeline is named after, not another event on it. */}
        <div
          className="absolute top-6 h-5 w-1 rounded-full bg-[var(--sev-4)]"
          style={{ left: `${landfallPosition}%` }}
        />
        <span
          className="absolute top-12 -translate-x-1/2 font-mono text-2xs text-[var(--text-muted)]"
          style={{ left: `${landfallPosition}%` }}
        >
          T+0
        </span>

        {milestones.map((milestone) => {
          const at = new Date(milestone.at).getTime();
          const position = positionOf(at, fromMs, toMs);
          return (
            <div
              key={milestone.id}
              className="absolute top-[26px] -translate-x-1/2"
              style={{ left: `${position}%` }}
            >
              <span
                className={cn(
                  'block size-2.5 rounded-full border-2 border-[var(--text-accent)]',
                  // Hollow for a projection, filled for something that happened. A
                  // forecast landfall drawn like a recorded one is a lie about certainty.
                  milestone.projected ? 'bg-[var(--surface-base)]' : 'bg-[var(--text-accent)]',
                )}
              />
            </div>
          );
        })}

        {/* Now. Drawn last so it sits above every milestone it may coincide with. */}
        <div
          className="absolute top-4 flex -translate-x-1/2 flex-col items-center"
          style={{ left: `${nowPosition}%` }}
        >
          <span className="rounded-full bg-[var(--text-primary)] px-2 py-0.5 font-mono text-2xs text-[var(--surface-base)]">
            {nowRelative}
          </span>
          <span className="h-5 w-px bg-[var(--text-primary)]" />
        </div>
      </div>

      <ol className="mt-2 flex flex-wrap gap-x-6 gap-y-1">
        {milestones.map((milestone) => (
          <li key={milestone.id} className="flex items-baseline gap-2 text-2xs">
            <span data-sarana-datum="" className="font-mono text-[var(--text-accent)]">
              {formatDisasterRelative(milestone.at, landfall)}
            </span>
            <span className="text-[var(--text-muted)]">{milestone.label}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export interface SpineNavButtonProps {
  readonly onClick: () => void;
  readonly label: string;
  readonly children: ReactNode;
}

/** A control docked into the spine. Kept here so the rail's chrome stays consistent. */
export function SpineNavButton({ onClick, label, children }: SpineNavButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        'min-h-[var(--touch-target-min)] rounded-[var(--radius-default)] px-3 text-xs',
        'text-[var(--text-muted)] hover:text-[var(--text-primary)]',
        FOCUS_RING,
      )}
    >
      {children}
    </button>
  );
}
