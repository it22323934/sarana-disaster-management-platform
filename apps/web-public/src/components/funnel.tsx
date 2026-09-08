/**
 * The funnel, drawn as proportional bars. A server component with no script.
 *
 * The design system's `TimeSpine` is a client component built for the console, where an
 * operator scrubs through an incident's milestones. Nothing here scrubs: the four stages
 * are fixed, they are read once, and pulling a client boundary onto `/` to draw four
 * rectangles would cost the route its JavaScript budget and its ability to render with
 * scripting off.
 *
 * **The bars are scaled against the first stage, not against each other.** A chart where
 * each bar filled its own row would show four full-width bars and say nothing; scaled
 * against assessed damage, the shape of the page *is* the finding — you can see where the
 * money stops without reading a single number.
 *
 * The width is also written into the row as text, because a bar is not accessible and a
 * bar is not copy-pasteable into an article.
 */

import type { ReactNode } from 'react';

export interface FunnelRow {
  readonly key: string;
  readonly label: ReactNode;
  readonly amount: number;
  /** Pre-formatted at the render boundary. */
  readonly formattedAmount: string;
  readonly formattedCount: string;
  /** Fraction of the previous stage, already formatted, or null for the first stage. */
  readonly ofPrevious: string | null;
  readonly ofPreviousLabel: ReactNode;
  readonly href: string;
  readonly description: ReactNode;
}

export function FunnelBars({
  rows,
  caption,
}: {
  readonly rows: readonly FunnelRow[];
  readonly caption: ReactNode;
}) {
  // The denominator is the first stage. If it is zero every bar is zero-width, which is
  // the correct rendering of "nothing has been assessed" rather than a divide-by-zero.
  const widest = rows[0]?.amount ?? 0;

  return (
    <section aria-label={typeof caption === 'string' ? caption : undefined}>
      <ol className="m-0 flex list-none flex-col gap-3 p-0">
        {rows.map((row) => {
          const percent = widest > 0 ? Math.max(0.5, (row.amount / widest) * 100) : 0;
          return (
            <li key={row.key}>
              <a
                href={row.href}
                className="block rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-3 no-underline hover:bg-[var(--surface-raised)]"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium text-[var(--text-primary)]">{row.label}</span>
                  <span
                    data-sarana-datum=""
                    className="font-semibold text-[var(--text-primary)]"
                  >
                    {row.formattedAmount}
                  </span>
                </div>

                {/* The bar is decoration; the row above and the line below carry the whole
                    meaning, so it is hidden from assistive technology rather than
                    announced as an unlabelled graphic. */}
                <div
                  aria-hidden="true"
                  className="mt-2 h-2 w-full overflow-hidden rounded-full bg-[var(--surface-raised)]"
                >
                  <div
                    className="h-full rounded-full bg-[var(--text-accent)]"
                    style={{ width: `${percent.toFixed(2)}%` }}
                  />
                </div>

                <p className="mt-2 text-xs text-[var(--text-muted)]">
                  {row.description}
                  {row.ofPrevious ? (
                    <>
                      {' '}
                      <span className="font-medium text-[var(--text-primary)]">
                        {row.ofPreviousLabel}
                      </span>
                    </>
                  ) : null}
                  {' · '}
                  <span data-sarana-datum="">{row.formattedCount}</span>
                </p>
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
