/**
 * The honesty components: MockDataBadge, ConfidenceMeter, OfflineIndicator, AuditTrail.
 *
 * Each of these exists to stop the interface asserting more than the platform knows.
 * There is no live integration with any Sri Lankan government system - the meteorology
 * feed, NBRO bulletins, the household registry, NIC verification, the bank disbursement
 * rail and the telco gateway are all mocks - and a demo must never let a viewer believe
 * otherwise.
 */

import type { Locale } from '@sarana/ts-shared/i18n';
import type { ReactNode } from 'react';

import { cn } from '../lib/cn.js';

export type ConfidenceBand = 'low' | 'medium' | 'high';

const MOCK_LABEL: Record<Locale, string> = {
  si: 'අනුකරණය කළ දත්ත',
  ta: 'உருவகப்படுத்தப்பட்ட தரவு',
  en: 'Simulated data',
};

const MOCK_EXPLANATION: Record<Locale, string> = {
  si: 'මෙම දත්ත රජයේ පද්ධතියක අනුකරණයකින් ලැබේ, සජීවී මූලාශ්‍රයකින් නොවේ.',
  ta: 'இந்தத் தரவு அரசாங்க அமைப்பின் உருவகப்படுத்தலிலிருந்து வருகிறது, நேரடி மூலத்திலிருந்து அல்ல.',
  en: 'This data comes from a simulated government system, not a live source.',
};

export interface MockDataBadgeProps {
  readonly locale?: Locale;
  /** Which mock produced the data, e.g. `dept-meteorology`. Rendered, not hidden. */
  readonly source?: string;
  readonly className?: string;
}

/**
 * Required on any surface rendering government-mock-derived data.
 *
 * There is no prop that hides it and no variant that shrinks it to an icon. A
 * `subtle` option would be used on the busiest screen in the product, which is exactly
 * the screen a viewer would take a screenshot of.
 *
 * The explanation is rendered as visible text rather than a `title`: a tooltip does not
 * open on the handset half of this platform's users are holding, and it does not survive
 * being screenshotted into an article.
 */
export function MockDataBadge({ locale = 'en', source, className }: MockDataBadgeProps) {
  return (
    <span
      role="status"
      data-sarana-simulated="true"
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[var(--radius-cell)] border px-2 py-1',
        'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
        'text-2xs font-medium',
        className,
      )}
    >
      <svg viewBox="0 0 12 12" className="size-3 shrink-0" aria-hidden="true">
        <path d="M6 1.5 11 10.5H1Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 5v2.2M6 8.6v.3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span>{MOCK_LABEL[locale]}</span>
      {source ? <span className="font-mono opacity-80">({source})</span> : null}
      <span className="sr-only">{MOCK_EXPLANATION[locale]}</span>
    </span>
  );
}

export interface ConfidenceMeterProps {
  /** 0 to 1. */
  readonly value: number;
  readonly band: ConfidenceBand;
  /** The band name in the active locale, e.g. "Medium". */
  readonly bandLabel: string;
  /**
   * What happens at this level, e.g. "routed to human review".
   *
   * Required, and this is the whole point of the component. A confidence number with no
   * consequence attached teaches an operator to ignore it: after a week of seeing "0.62"
   * with nothing following from it, 0.62 stops being information. What the reader needs
   * is not the number but what the platform is going to do about it.
   */
  readonly consequence: string;
  readonly className?: string;
}

const BAND_CLASSES: Record<ConfidenceBand, string> = {
  // Cool throughout: confidence is not a hazard level, and a red confidence meter beside
  // an amber severity chip is two colour languages on one card.
  low: 'text-[var(--pending)]',
  medium: 'text-[var(--text-muted)]',
  high: 'text-[var(--verified)]',
};

/** How many of the three segments are filled. Shape, so it is not colour alone. */
const BAND_SEGMENTS: Record<ConfidenceBand, number> = { low: 1, medium: 2, high: 3 };

export function ConfidenceMeter({
  value,
  band,
  bandLabel,
  consequence,
  className,
}: ConfidenceMeterProps) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  const filled = BAND_SEGMENTS[band];

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-center gap-2">
        <span
          role="meter"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${bandLabel}: ${consequence}`}
          className={cn('inline-flex gap-0.5', BAND_CLASSES[band])}
        >
          {[0, 1, 2].map((segment) => (
            <span
              key={segment}
              className={cn(
                'h-3 w-2 rounded-[1px] border border-current',
                segment < filled ? 'bg-current' : 'bg-transparent',
              )}
            />
          ))}
        </span>
        <span className={cn('text-xs font-medium', BAND_CLASSES[band])}>{bandLabel}</span>
        <span data-sarana-datum="" className="font-mono text-xs text-[var(--text-muted)]">
          {percent}%
        </span>
      </div>
      {/* Visible, not a tooltip. The consequence is the reason the number is on screen. */}
      <span className="text-2xs text-[var(--text-muted)]">{consequence}</span>
    </div>
  );
}

export interface OfflineIndicatorProps {
  readonly online: boolean;
  /** Number of writes waiting to sync. Rendered whenever it is above zero. */
  readonly queued?: number;
  readonly onlineLabel: string;
  readonly offlineLabel: string;
  /** e.g. "3 reports waiting to send". The caller formats the count into it. */
  readonly queuedLabel?: (count: number) => string;
  readonly className?: string;
}

/**
 * Connectivity, and what is waiting because of it.
 *
 * The queue depth is the part that matters. A GN officer working through a division with
 * no signal needs to know that eleven assessments are held locally and will go when the
 * handset finds a tower - "offline" alone reads as "your work is lost", which is the one
 * thing it must never imply on an offline-first platform.
 */
export function OfflineIndicator({
  online,
  queued = 0,
  onlineLabel,
  offlineLabel,
  queuedLabel,
  className,
}: OfflineIndicatorProps) {
  return (
    <div
      // Polite, not assertive: connectivity flaps, and an assertive region would
      // interrupt a screen reader mid-word every time a tower is lost and regained.
      role="status"
      aria-live="polite"
      className={cn(
        'inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-2xs',
        online
          ? 'border-[var(--divider)] text-[var(--text-muted)]'
          : 'border-[var(--pending)] text-[var(--pending)]',
        className,
      )}
    >
      <svg viewBox="0 0 12 12" className="size-3 shrink-0" aria-hidden="true">
        {online ? (
          <path d="M6 1.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Z" fill="currentColor" />
        ) : (
          <path
            d="M6 1.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9ZM3 3l6 6"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        )}
      </svg>
      <span>{online ? onlineLabel : offlineLabel}</span>
      {queued > 0 && queuedLabel ? (
        <span className="font-medium">{queuedLabel(queued)}</span>
      ) : null}
    </div>
  );
}

export interface AuditEntry {
  readonly id: string;
  /** UTC ISO-8601, already formatted for display by the caller. */
  readonly at: ReactNode;
  /** Who or what acted. An agent name, a role - never a person's name. */
  readonly actor: ReactNode;
  readonly action: ReactNode;
  /** The correlation id that ties this step to the rest of the chain. */
  readonly correlationId?: string;
}

export interface AuditTrailProps {
  readonly entries: readonly AuditEntry[];
  /** Names the list, e.g. "Approval history". Localised by the caller. */
  readonly label: string;
  readonly className?: string;
}

/**
 * The chain of who did what, in order.
 *
 * Rendered as an ordered list because the order is the content: an approval that came
 * after a disbursement is a finding, and it is only visible if the sequence is preserved
 * and numbered. The correlation id is shown rather than hidden, because it is what an
 * auditor uses to follow one household's money from the citizen's first report through
 * to the ledger entry.
 *
 * Actors are roles and agent names. No personal names appear here - the queries behind
 * this never select one, which is a stronger guarantee than redaction.
 */
export function AuditTrail({ entries, label, className }: AuditTrailProps) {
  return (
    <ol aria-label={label} className={cn('flex flex-col', className)}>
      {entries.map((entry, index) => (
        <li
          key={entry.id}
          className={cn(
            'grid grid-cols-[auto_1fr] gap-x-3 border-l border-[var(--divider)] pb-4 pl-4',
            // The last entry drops the rail below it, so the chain visibly ends rather
            // than trailing off as though there were more.
            index === entries.length - 1 && 'border-l-transparent pb-0',
          )}
        >
          <span
            aria-hidden="true"
            className="-ml-[21px] mt-1 size-2 rounded-full bg-[var(--text-accent)]"
          />
          <div className="col-start-2 flex flex-col gap-0.5">
            <span data-sarana-datum="" className="font-mono text-2xs text-[var(--text-muted)]">
              {entry.at}
            </span>
            <span className="text-sm text-[var(--text-primary)]">{entry.action}</span>
            <span className="text-xs text-[var(--text-muted)]">{entry.actor}</span>
            {entry.correlationId ? (
              <span
                data-sarana-datum=""
                className="font-mono text-2xs text-[var(--text-muted)] opacity-80"
              >
                {entry.correlationId}
              </span>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
