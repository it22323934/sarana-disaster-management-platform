'use client';

/**
 * The calculation, rendered as a readable derivation.
 *
 * Extracted from the money gate so `/approvals/[id]` and `/disbursements/[id]` render the
 * *same* trace rather than each having its own renderer. Two renderers would eventually
 * omit different steps, and the whole argument for this panel is that it omits none: the
 * step it drops is the one the approver needed.
 *
 * `calculation_trace` is whatever `ledger-svc` recorded, so this walks it structurally
 * rather than assuming a shape. A key this component has never seen is rendered, not
 * dropped. An approver shown only a number is being asked to rubber-stamp; one who can
 * follow the arithmetic catches the schedule version being wrong, which is the error that
 * actually happens.
 *
 * The schedule version goes above the steps and the amount below them, so the panel reads
 * top to bottom as "under this schedule, by these steps, this much".
 */

import { LKRAmount, cn } from '@sarana/ui';
import { useTranslations } from 'next-intl';

export interface CalculationTraceProps {
  readonly trace: Record<string, unknown>;
  readonly scheduleVersion: string;
  readonly amountCents: number;
  readonly className?: string;
}

export function CalculationTrace({
  trace,
  scheduleVersion,
  amountCents,
  className,
}: CalculationTraceProps) {
  const t = useTranslations('disbursement');
  const entries = Object.entries(trace);

  return (
    <div
      className={cn(
        'rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4',
        className,
      )}
    >
      <dl className="flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {t('scheduleVersion')}
          </dt>
          <dd data-sarana-datum="" className="font-mono text-sm">
            {scheduleVersion}
          </dd>
        </div>

        {entries.length === 0 ? (
          // An empty trace is a real and alarming state: an entitlement whose working was
          // never recorded cannot be checked by anybody. Said plainly rather than rendered
          // as a panel with a schedule version and a total and nothing between them, which
          // would look like a simple calculation instead of an absent one.
          <p className="text-xs text-[var(--sev-2-fg)]">{t('traceEmpty')}</p>
        ) : (
          entries.map(([key, value]) => (
            <div key={key} className="flex flex-wrap items-baseline gap-2">
              <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{key}</dt>
              <dd data-sarana-datum="" className="font-mono text-xs">
                {renderTraceValue(value)}
              </dd>
            </div>
          ))
        )}

        <div className="mt-2 flex flex-wrap items-baseline gap-2 border-t border-[var(--divider)] pt-2">
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {t('finalAmount')}
          </dt>
          <dd>
            <LKRAmount cents={amountCents} className="text-base font-semibold" />
          </dd>
        </div>
      </dl>
    </div>
  );
}

/**
 * One trace value as text.
 *
 * Exported for the unit test that pins the "nothing is dropped" rule. `null` renders as a
 * dash rather than as nothing, because a step recorded as null is a step that ran and
 * produced no value - which is different from a step that was not recorded.
 */
export function renderTraceValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
