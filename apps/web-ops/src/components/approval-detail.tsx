'use client';

/**
 * `/approvals/[id]` — one entitlement, before it is signed.
 *
 * The queue at `/approvals` says *what* is waiting and for which level. This screen is
 * where somebody actually reads the calculation and decides, and it is deliberately the
 * same trace the money gate renders rather than a summary of it.
 *
 * **The derivation, not the total.** An approver shown only a figure is being asked to
 * rubber-stamp; one who can follow the arithmetic catches the schedule version being
 * wrong, which is the error that actually happens. `DisbursementGate` already walks
 * `calculation_trace` key by key, so this screen reuses that component rather than
 * building a second renderer that can omit a different step.
 *
 * **Approving is not releasing, and the screen says so twice.** An approver signs that the
 * calculation is right for this household; a different person confirms the money should
 * move now, and `ledger-svc` refuses a release by whoever approved it. Somebody who
 * believes they have paid a household when they have only approved it stops chasing the
 * payment.
 *
 * **The household is a reference, never a name.** Same rule as the money gate: the
 * approver does not need one and does not get one. The guarantee is that the query never
 * selects a name; this screen is the second line.
 */

import { Badge, Button, LKRAmount, ReferenceCode, RelativeTime, Skeleton } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import { useEntitlement, useGrievances } from '../lib/queries';
import { isOpenGrievance, levelsRequiredFor } from '../lib/schemas';
import { CalculationTrace } from './calculation-trace';
import { ErrorPanel } from './degraded';

export interface ApprovalDetailProps {
  readonly entitlementId: string;
}

export function ApprovalDetail({ entitlementId }: ApprovalDetailProps) {
  const t = useTranslations('approvals');
  const d = useTranslations('disbursement');
  const cop = useTranslations('cop');

  const entitlement = useEntitlement(entitlementId);
  const grievances = useGrievances(entitlementId);

  if (entitlement.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (entitlement.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={entitlement.error}>
          <Button asChild variant="secondary" size="sm" className="mt-2 self-start">
            <Link href="/approvals">{t('title')}</Link>
          </Button>
        </ErrorPanel>
      </div>
    );
  }

  const record = entitlement.data;
  const required = levelsRequiredFor(record.calculated_lkr_cents);
  const recorded = new Set(
    record.approvals
      .filter((approval) => approval.decision === 'APPROVED')
      .map((approval) => approval.level)
      .filter((level): level is string => level !== undefined),
  );
  const outstanding = required.filter((level) => !recorded.has(level));
  const open = (grievances.data ?? []).filter(isOpenGrievance);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t('detailTitle')}</h1>
        <ReferenceCode code={record.assessment_ref} kind={cop('reference')} />
        <Badge tone="neutral">{record.status}</Badge>
        <LKRAmount
          cents={record.calculated_lkr_cents}
          className="ml-auto text-lg font-semibold"
        />
      </header>

      <dl className="grid gap-4 rounded-[var(--radius-default)] border border-[var(--divider)] p-4 sm:grid-cols-3">
        <Definition label={cop('division')} value={record.gn_division_code} />
        {/* The household reference, never the name. */}
        <Definition label={d('household')} value={record.household_id.slice(0, 8)} />
        <Definition label={d('scheduleVersion')} value={record.cost_schedule_version} />
      </dl>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('waitingFor')}</h2>
        <div className="flex flex-wrap gap-2">
          {required.map((level) => (
            <Badge key={level} tone={recorded.has(level) ? 'verified' : 'pending'}>
              {recorded.has(level) ? t('signedAt', { level }) : t('needs', { level })}
            </Badge>
          ))}
        </div>
        {/* Which threshold decided that, said out loud. An approver who cannot see why
            District is required cannot tell a misconfigured schedule from a large claim. */}
        <p className="text-2xs text-[var(--text-muted)]">
          {required.length > 1 ? t('twoLevelsBecause') : t('oneLevelBecause')}
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{d('approvals')}</h2>
        {record.approvals.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">{t('noApprovalsYet')}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {record.approvals.map((approval, index) => (
              <li
                key={`${approval.level}-${approval.approver_id ?? index}`}
                className="flex flex-wrap items-center gap-3 text-xs"
              >
                <Badge tone={approval.decision === 'APPROVED' ? 'verified' : 'neutral'}>
                  {approval.level ?? '—'}
                </Badge>
                <span className="text-[var(--text-muted)]">{approval.decision}</span>
                {/* The approver's id, not their name. Attribution without identification:
                    an auditor can follow it to a person through the directory; this screen
                    does not put one on a claim page. */}
                <span data-sarana-datum="" className="font-mono text-2xs">
                  {approval.approver_id?.slice(0, 8) ?? '—'}
                </span>
                {approval.decided_at ? <RelativeTime value={approval.decided_at} /> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Shown here as well as at the money gate. An approver who signs an entitlement
          with an open grievance has spent their signature on work the release will refuse,
          and finding that out at the gate is finding out after the fact. */}
      {open.length > 0 ? (
        <section
          role="alert"
          className="flex flex-col gap-1 rounded-[var(--radius-default)] border-2 border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] px-4 py-3 text-[var(--sev-3-fg)]"
        >
          <h2 className="text-sm font-semibold">{d('grievanceOpen')}</h2>
          <p className="text-xs opacity-90">{d('grievanceExplanation')}</p>
          <ul className="flex flex-col gap-1 text-xs">
            {open.map((grievance) => (
              <li key={grievance.id} className="flex flex-wrap items-center gap-2">
                <ReferenceCode code={grievance.public_ref ?? grievance.id.slice(0, 8)} />
                <Badge tone="pending">{grievance.status}</Badge>
                {grievance.category ? <span>{grievance.category}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{d('calculation')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{d('calculationHint')}</p>
        <CalculationTrace
          trace={record.calculation_trace}
          scheduleVersion={record.cost_schedule_version}
          amountCents={record.calculated_lkr_cents}
        />
      </section>

      <section className="flex flex-col gap-2 rounded-[var(--radius-default)] border border-[var(--pending)] p-4">
        <h2 className="text-sm font-medium">{t('signTitle')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{t('notARelease')}</p>
        {outstanding.length === 0 ? (
          <p className="text-xs text-[var(--verified)]">{t('fullyApproved')}</p>
        ) : (
          // Signing itself lives on the queue screen, where the second factor is collected
          // beside the row. Two places to sign would be two idempotency keys for the same
          // signature, and the queue is where an approver works through them in order.
          <Button asChild variant="primary" className="self-start">
            <Link href="/approvals">{t('signOnQueue', { level: outstanding[0] ?? 'DS' })}</Link>
          </Button>
        )}
        <Button asChild variant="secondary" size="sm" className="self-start">
          <Link href={`/disbursements/${record.id}`}>{d('title')}</Link>
        </Button>
      </section>
    </div>
  );
}

function Definition({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd data-sarana-datum="" className="font-mono text-sm">
        {value}
      </dd>
    </div>
  );
}
