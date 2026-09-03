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
  MapLegend,
  MapShell,
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

  function persist(next: Layout): void {
    setLayout(next);
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(next));
    } catch {
      // Layout is a convenience. Losing it is not worth an error message.
    }
  }

  const rows = queue.data ?? [];
  // True when nothing in the queue carries an agent-produced score. That is the platform's
  // state today — the triage agent has no adapters — and the operator has to be told.
  const assistedRanking = rows.some((row) => row.triage_score !== null);

  const styleUrl = process.env.NEXT_PUBLIC_SARANA_MAP_STYLE_URL ?? '';

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-3 p-4">
      {!assistedRanking && rows.length > 0 ? <DegradedBanner kind="agent" /> : null}

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
        />

        <section
          aria-label={t('map')}
          style={{ width: `${layout.map}%` }}
          className="min-w-[16rem] overflow-hidden rounded-[var(--radius-default)] border border-[var(--divider)]"
        >
          <MapShell
            styleUrl={styleUrl}
            label={t('map')}
            className="h-full w-full"
            fallback={
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-medium">{t('mapFallback')}</h3>
                {/* The same facts as the map, as a list. Not a summary of it — this is
                    what a screen reader user, a printed situation report and a browser
                    that failed to load tiles all get. */}
                <ul className="flex flex-col gap-1">
                  {rows.map((row) => (
                    <li key={row.id} className="flex items-center gap-2 text-xs">
                      <SeverityPill level={row.severity as SeverityLevel} locale="en" />
                      <span data-sarana-datum="" className="font-mono">
                        {row.gn_division_code}
                      </span>
                      <span>{row.public_ref}</span>
                    </li>
                  ))}
                </ul>
              </div>
            }
          />
        </section>

        <Divider
          onDrag={(delta) => persist({ ...layout, map: clamp(layout.map + delta, 20, 60) })}
          label={t('map')}
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

      <MapLegend
        title={t('layers')}
        levels={[2, 3, 4]}
        labels={{ 0: '0', 1: '1', 2: '2', 3: '3', 4: '4' }}
        className="max-w-xs"
      />
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
 */
function Divider({
  onDrag,
  label,
}: {
  readonly onDrag: (deltaPercent: number) => void;
  readonly label: string;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
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

function QueueRowItem({
  row,
  rank,
  selected,
  onSelect,
}: {
  readonly row: QueueRow;
  readonly rank: number;
  readonly selected: boolean;
  readonly onSelect: () => void;
}) {
  const t = useTranslations('cop');
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'flex w-full flex-col gap-1 border-b border-[var(--divider)] px-3 py-2 text-left',
          'min-h-[var(--touch-target-min)] transition-colors duration-[var(--motion-state)]',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--focus-ring)]',
          selected ? 'bg-[var(--surface-card)]' : 'hover:bg-[var(--surface-raised)]',
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
          <RelativeTime value={row.first_reported_at} />
        </span>
      </button>
    </li>
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

      {assisted && row.triage_factors && row.triage_factors.length > 0 ? (
        <section>
          <h3 className="mb-1 text-sm font-medium">{t('whyThisRank')}</h3>
          <ul className="flex flex-col gap-1">
            {row.triage_factors.map((factor) => (
              <li key={factor.name} className="flex items-baseline justify-between text-xs">
                <span>{factor.name}</span>
                <span data-sarana-datum="" className="font-mono">
                  {factor.contribution.toFixed(2)}
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
