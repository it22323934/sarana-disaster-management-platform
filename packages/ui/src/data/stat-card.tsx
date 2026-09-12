'use client';

// This module holds a hook, a browser API, or a prop that is a function, so it runs on
// the client. The directive is deliberately not on every file in the library: badge,
// skeleton, severity-pill and trust are pure renderers and stay server-renderable,
// which is what keeps the public dashboard's pages static.

/**
 * StatCard, TrendSparkline, EmptyState and Pagination.
 *
 * The rule these share: a number on a dashboard during a disaster is read by someone who
 * will act on it, so none of them renders a figure without saying what it counts, when it
 * was counted, and - where it applies - that the source is a mock.
 */

import type { ReactNode } from 'react';

import { cn } from '../lib/cn.js';
import { FOCUS_RING } from '../lib/focus.js';
import { Button } from '../primitives/button.js';

export interface StatCardProps {
  readonly label: ReactNode;
  /** Pre-formatted. Format at the render boundary with `@sarana/ts-shared/format`. */
  readonly value: ReactNode;
  /** What the figure counts and over what window. Not decoration - see the docstring. */
  readonly context?: ReactNode;
  /**
   * When this figure was last recomputed, already formatted.
   *
   * A stat with no timestamp on an incident dashboard is the most dangerous element in
   * this library: it looks live and may be an hour old.
   */
  readonly asOf: ReactNode;
  /** Rendered under the value. `MockDataBadge`, `SeverityPill`, a trend, and so on. */
  readonly footer?: ReactNode;
  readonly className?: string;
}

export function StatCard({ label, value, context, asOf, footer, className }: StatCardProps) {
  return (
    <div
      className={cn(
        'flex flex-col gap-1 rounded-[var(--radius-default)] border border-[var(--divider)]',
        'bg-[var(--surface-card)] p-4',
        className,
      )}
    >
      <span className="text-2xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </span>
      <span
        data-sarana-datum=""
        className="text-2xl font-semibold leading-none text-[var(--text-primary)]"
      >
        {value}
      </span>
      {context ? <span className="text-xs text-[var(--text-muted)]">{context}</span> : null}
      <span className="mt-1 text-2xs text-[var(--text-muted)]">{asOf}</span>
      {footer ? <div className="mt-2">{footer}</div> : null}
    </div>
  );
}

export interface TrendSparklineProps {
  /** Oldest first. Rendered as a path; no axis, no gridlines, no interaction. */
  readonly points: readonly number[];
  /**
   * What the line shows, for a screen reader and for anyone who cannot resolve a 24px
   * graphic. The sparkline itself is `aria-hidden` and this carries the whole meaning.
   */
  readonly summary: string;
  readonly width?: number;
  readonly height?: number;
  readonly className?: string;
}

export function TrendSparkline({
  points,
  summary,
  width = 96,
  height = 24,
  className,
}: TrendSparklineProps) {
  if (points.length < 2) {
    // One point is not a trend. Rendering a flat line for it would assert something the
    // data does not say.
    return <span className="text-xs text-[var(--text-muted)]">{summary}</span>;
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  // A flat series would divide by zero; drawing it mid-height is the honest rendering.
  const span = max - min || 1;
  const step = width / (points.length - 1);

  const path = points
    .map((point, index) => {
      const x = index * step;
      const y = height - ((point - min) / span) * height;
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        aria-hidden="true"
        className="overflow-visible"
      >
        <path
          d={path}
          fill="none"
          // Cool, like every other interface accent: a trend line is not a severity.
          stroke="var(--text-accent)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="sr-only">{summary}</span>
    </span>
  );
}

export interface EmptyStateProps {
  readonly title: ReactNode;
  /**
   * Why it is empty and what to do next.
   *
   * "No results" alone is a dead end. During an incident the difference between "no
   * incidents in this division" and "the filter excludes them" changes what an operator
   * does in the next thirty seconds.
   */
  readonly description: ReactNode;
  readonly action?: ReactNode;
  readonly className?: string;
}

export function EmptyState({ title, description, action, className }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center gap-2 px-6 py-12 text-center', className)}>
      <p className="text-base font-medium text-[var(--text-primary)]">{title}</p>
      <p className="max-w-prose text-sm text-[var(--text-muted)]">{description}</p>
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export interface PaginationProps {
  /**
   * Cursor pagination, matching the API.
   *
   * There are no page numbers because the API has no offsets: `?cursor=&limit=` is the
   * convention across every SARANA service, and a page-number control would be lying
   * about being able to jump.
   */
  readonly onPrevious?: () => void;
  readonly onNext?: () => void;
  readonly hasPrevious: boolean;
  readonly hasNext: boolean;
  readonly previousLabel: string;
  readonly nextLabel: string;
  /** e.g. "Showing 50 of about 1,200". Pre-formatted and localised by the caller. */
  readonly summary: ReactNode;
  /**
   * Names the landmark, e.g. "Incident queue pages".
   *
   * A plain string, not the summary: `summary` is a ReactNode and may be a fragment, and
   * an `aria-label` built from one renders as "[object Object]" to a screen reader. A
   * page with three paginated regions needs three distinguishable names.
   */
  readonly label: string;
  readonly className?: string;
}

export function Pagination({
  onPrevious,
  onNext,
  hasPrevious,
  hasNext,
  previousLabel,
  nextLabel,
  summary,
  label,
  className,
}: PaginationProps) {
  return (
    <nav
      aria-label={label}
      className={cn('flex items-center justify-between gap-4 py-2', className)}
    >
      <span className="text-xs text-[var(--text-muted)]">{summary}</span>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={onPrevious}
          disabled={!hasPrevious}
          className={FOCUS_RING}
        >
          {previousLabel}
        </Button>
        <Button size="sm" onClick={onNext} disabled={!hasNext} className={FOCUS_RING}>
          {nextLabel}
        </Button>
      </div>
    </nav>
  );
}
