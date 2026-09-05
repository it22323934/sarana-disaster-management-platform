'use client';

/**
 * `/ops` — the common operating picture.
 *
 * Three panes: the triage queue, the map, and the context for whatever is selected. The
 * split is resizable and the layout persists per user, because an operator running a
 * flood works the queue and an operator running a landslide works the map, and neither
 * should have to redo the layout every shift.
 *
 * **On the ordering.** The queue is ordered by triage score when the triage agent has
 * produced one and by the deterministic fallback when it has not — and the difference is
 * stated on screen. Rendering a rule-based rank as if it were the model's is the single
 * most misleading thing this console could do, because it invites an operator to trust an
 * ordering that nothing intelligent produced.
 */

import {
  EmptyState,
  PopoverContent,
  PopoverRoot,
  PopoverTrigger,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  cn,
} from '@sarana/ui';
import type { SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { useTriageQueue } from '../lib/queries';
import type { QueueRow } from '../lib/schemas';
import { DegradedBanner, ErrorPanel } from './degraded';
import { SituationMap } from './situation-map';

const LAYOUT_KEY = 'sarana.ops.layout';

/** Percentage widths of the three panes. Persisted per browser, not per server session. */
interface Layout {
  readonly queue: number;
  readonly map: number;
}

const DEFAULT_LAYOUT: Layout = { queue: 30, map: 45 };

function readLayout(): Layout {
  if (typeof window === 'undefined') return DEFAULT_LAYOUT;
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<Layout>;
    return {
      queue: typeof parsed.queue === 'number' ? parsed.queue : DEFAULT_LAYOUT.queue,
      map: typeof parsed.map === 'number' ? parsed.map : DEFAULT_LAYOUT.map,
    };
  } catch {
    // A private window, cleared storage, or a browser blocking site data. The default
    // layout is a complete answer, so this is not worth surfacing.
    return DEFAULT_LAYOUT;
  }
}

export function CommonOperatingPicture() {
  const t = useTranslations('cop');
  const queue = useTriageQueue();
  const [selected, setSelected] = useState<QueueRow | null>(null);
  const [layout, setLayout] = useState<Layout>(DEFAULT_LAYOUT);

  // Read after mount: `localStorage` does not exist on the server and reading it during
  // render would hydrate mismatched.
  useEffect(() => setLayout(readLayout()), []);

  /**
   * One clock for the whole queue.
   *
   * Ticking every thirty seconds so rows age on screen between polls: an operator who
   * walked away must come back to a queue whose ages have moved, not to one frozen at the
   * last fetch. Shared rather than per-row so every row ages against the same instant -
   * two rows a second apart must not straddle the threshold because they rendered in
   * different ticks.
   */
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  function persist(next: Layout): void {
    setLayout(next);
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(next));
    } catch {
      // Layout is a convenience. Losing it is not worth an error message.
    }
  }

  const rows = queue.data?.entries ?? [];

  /**
   * Whether an agent produced this ordering.
   *
   * Read from the response, never inferred. `incident-svc` computes a score for every row
   * from the published rule when nothing has stored one - so "has a score" is always true
   * and inferring from it would mean the degraded banner never appeared. The `assisted`
   * flag is the only thing that knows.
   */
  const assistedRanking = queue.data?.assisted ?? false;

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-3 p-4">
      {/* The console's own trilingual banner rather than the server's `banner` string,
          which is English only. The ordering rule is shown beside it, because "manual
          ordering" is less useful to a dispatcher than the name of the rule doing it. */}
      {!assistedRanking && rows.length > 0 ? (
        <div className="flex flex-col gap-1">
          <DegradedBanner kind="agent" />
          {queue.data?.ordering ? (
            <p className="text-2xs text-[var(--text-muted)]">
              {t('orderedBy')}:{' '}
              <span data-sarana-datum="" className="font-mono">
                {queue.data.ordering}
              </span>
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 gap-3">
        <section
          aria-label={t('queue')}
          style={{ width: `${layout.queue}%` }}
          className="flex min-w-[18rem] flex-col overflow-hidden rounded-[var(--radius-default)] border border-[var(--divider)]"
        >
          <h2 className="border-b border-[var(--divider)] px-3 py-2 text-sm font-medium">
            {t('queue')}
          </h2>
          {queue.isPending ? (
            <div className="flex flex-col gap-2 p-3">
              <Skeleton line />
              <Skeleton line />
              <Skeleton line />
            </div>
          ) : queue.isError ? (
            <ErrorPanel error={queue.error} className="m-3" />
          ) : rows.length === 0 ? (
            <EmptyState title={t('queueEmpty')} description={t('queueEmptyHint')} />
          ) : (
            <ol className="flex-1 overflow-y-auto">
              {rows.map((row, index) => (
                <QueueRowItem
                  key={row.id}
                  row={row}
                  rank={index + 1}
                  selected={selected?.id === row.id}
                  onSelect={() => setSelected(row)}
                  now={now}
                />
              ))}
            </ol>
          )}
        </section>

        <Divider
          onDrag={(delta) =>
            persist({ ...layout, queue: clamp(layout.queue + delta, 20, 50) })
          }
          label={t('queue')}
          value={layout.queue}
          min={20}
          max={50}
        />

        <section
          aria-label={t('map')}
          style={{ width: `${layout.map}%` }}
          className="min-w-[16rem] overflow-hidden rounded-[var(--radius-default)] border border-[var(--divider)] p-2"
        >
          <SituationMap rows={rows} className="flex h-full flex-col" />
        </section>

        <Divider
          onDrag={(delta) => persist({ ...layout, map: clamp(layout.map + delta, 20, 60) })}
          label={t('map')}
          value={layout.map}
          min={20}
          max={60}
        />

        <section
          aria-label={t('context')}
          className="flex min-w-[16rem] flex-1 flex-col overflow-y-auto rounded-[var(--radius-default)] border border-[var(--divider)] p-3"
        >
          <h2 className="mb-2 text-sm font-medium">{t('context')}</h2>
          {selected ? (
            <SelectedIncident row={selected} assisted={assistedRanking} />
          ) : (
            <EmptyState title={t('contextEmpty')} description={t('contextEmptyHint')} />
          )}
        </section>
      </div>

    </div>
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * A keyboard-operable pane divider.
 *
 * `separator` with arrow-key handling rather than a drag-only handle: the console must be
 * fully operable from the keyboard, and a divider that can only be dragged makes the
 * layout unreachable for a dispatcher working without a pointer.
 *
 * A **focusable** separator is a window splitter in ARIA terms, and a splitter must carry
 * its position: `aria-valuenow` with its bounds. Without them a screen reader announces
 * "separator" and nothing else, so a user can move the divider and never learn whether it
 * moved. The axe sweep caught this as a critical violation, which is what that sweep is
 * for.
 */
function Divider({
  onDrag,
  label,
  value,
  min,
  max,
}: {
  readonly onDrag: (deltaPercent: number) => void;
  readonly label: string;
  readonly value: number;
  readonly min: number;
  readonly max: number;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(value)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          onDrag(-2);
        }
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          onDrag(2);
        }
      }}
      className={cn(
        'w-1 shrink-0 cursor-col-resize rounded-full bg-[var(--divider)]',
        'hover:bg-[var(--text-accent)] focus-visible:outline-2',
        'focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]',
      )}
    />
  );
}

/**
 * How old a row has to be before it starts reading as waiting.
 *
 * Twenty minutes. Long enough that a busy queue is not a wall of pending-blue, short
 * enough that an incident nobody has touched for a shift is unmissable. The colour is
 * `--pending`, which on this platform means exactly one thing - a human has to act - and
 * an incident sitting unworked in the queue is precisely that.
 */
const AGEING_AFTER_SECONDS = 20 * 60;

function ageOf(row: QueueRow, now: Date): number {
  return Math.max(0, (now.getTime() - new Date(row.first_reported_at).getTime()) / 1000);
}

function QueueRowItem({
  row,
  rank,
  selected,
  onSelect,
  now,
}: {
  readonly row: QueueRow;
  readonly rank: number;
  readonly selected: boolean;
  readonly onSelect: () => void;
  readonly now: Date;
}) {
  const t = useTranslations('cop');
  const ageing = ageOf(row, now) >= AGEING_AFTER_SECONDS;

  return (
    <li>
      <div
        className={cn(
          'flex items-start gap-1 border-b border-[var(--divider)]',
          selected ? 'bg-[var(--surface-card)]' : 'hover:bg-[var(--surface-raised)]',
        )}
      >
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected ? 'true' : undefined}
          className={cn(
            'flex min-h-[var(--touch-target-min)] flex-1 flex-col gap-1 px-3 py-2 text-left',
            'transition-colors duration-[var(--motion-state)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--focus-ring)]',
          )}
        >
          <span className="flex items-center gap-2">
            <span data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
              {rank}
            </span>
            <SeverityPill level={row.severity as SeverityLevel} locale="en" />
            <ReferenceCode code={row.public_ref} />
          </span>
          <span className="flex flex-wrap items-baseline gap-x-3 text-2xs text-[var(--text-muted)]">
            <span data-sarana-datum="" className="font-mono">
              {row.gn_division_code}
            </span>
            <span>
              {t('peopleAtRisk')}:{' '}
              <span data-sarana-datum="" className="font-mono">
                {row.people_at_risk}
              </span>
            </span>
            {/* The age turns `--pending` as it ages. Not a severity colour: how long an
                incident has waited is a fact about this console's queue, not about the
                hazard, and painting it amber would say the hazard got worse. */}
            <span
              data-ageing={ageing}
              className={ageing ? 'font-medium text-[var(--pending)]' : undefined}
            >
              <RelativeTime value={row.first_reported_at} now={now} />
            </span>
          </span>
        </button>

        <FactorBreakdown row={row} />
      </div>
    </li>
  );
}

/**
 * Why this row sits where it does, one click away and without leaving the screen.
 *
 * A popover rather than a detail pane: an operator comparing row 3 against row 4 has to
 * see both reasons in the same few seconds, and a pane that replaces the context panel
 * loses the row they were comparing against.
 */
function FactorBreakdown({ row }: { readonly row: QueueRow }) {
  const t = useTranslations('cop');

  const factors = Object.entries(row.factors ?? {})
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));

  return (
    <PopoverRoot>
      <PopoverTrigger
        aria-label={t('whyThisRank')}
        className={cn(
          'mr-1 mt-2 shrink-0 rounded-[var(--radius-cell)] px-2 py-1 text-2xs',
          'text-[var(--text-muted)] hover:text-[var(--text-accent)]',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]',
        )}
      >
        {row.score === null ? '—' : row.score.toFixed(2)}
      </PopoverTrigger>
      <PopoverContent>
        <h3 className="mb-2 text-sm font-medium">{t('whyThisRank')}</h3>
        <p className="mb-2 text-2xs text-[var(--text-muted)]">
          {t('orderedBy')}:{' '}
          <span data-sarana-datum="" className="font-mono">
            {row.model_version ?? '—'}
          </span>
        </p>
        {factors.length === 0 ? (
          // Not an empty list under a "why" heading, which would read as "nothing counted".
          <p className="text-xs text-[var(--text-muted)]">{t('noFactors')}</p>
        ) : (
          <dl className="flex flex-col gap-1">
            {factors.map(([name, value]) => (
              <div key={name} className="flex items-baseline justify-between gap-4 text-xs">
                <dt>{name}</dt>
                <dd data-sarana-datum="" className="font-mono">
                  {value.toFixed(3)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </PopoverContent>
    </PopoverRoot>
  );
}

/**
 * The context pane.
 *
 * `whyThisRank` is present only when there is a real answer. An empty factor list rendered
 * under that heading would read as "the agent considered nothing", which is a different
 * and worse claim than "no agent ranked this".
 */
function SelectedIncident({
  row,
  assisted,
}: {
  readonly row: QueueRow;
  readonly assisted: boolean;
}) {
  const t = useTranslations('cop');

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityPill level={row.severity as SeverityLevel} locale="en" />
        <ReferenceCode code={row.public_ref} kind={t('reference')} />
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <Definition label={t('division')} value={row.gn_division_code} datum />
        <Definition label={t('peopleAtRisk')} value={String(row.people_at_risk)} datum />
        <Definition label={t('severity')} value={String(row.severity)} datum />
        <Definition label={t('age')} value="" >
          <RelativeTime value={row.first_reported_at} />
        </Definition>
      </dl>

      {assisted && row.factors && Object.keys(row.factors).length > 0 ? (
        <section>
          <h3 className="mb-1 text-sm font-medium">{t('whyThisRank')}</h3>
          <ul className="flex flex-col gap-1">
            {Object.entries(row.factors)
              .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
              .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
              .map(([name, value]) => (
                <li key={name} className="flex items-baseline justify-between text-xs">
                  <span>{name}</span>
                  <span data-sarana-datum="" className="font-mono">
                    {value.toFixed(3)}
                  </span>
                </li>
              ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Definition({
  label,
  value,
  datum = false,
  children,
}: {
  readonly label: string;
  readonly value: string;
  readonly datum?: boolean;
  readonly children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col">
      <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd {...(datum ? { 'data-sarana-datum': '' } : {})} className={datum ? 'font-mono' : ''}>
        {children ?? value}
      </dd>
    </div>
  );
}
