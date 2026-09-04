'use client';

/**
 * The money gate screen.
 *
 * `ledger-svc` enforces six independent things before a rupee moves: area scope, a second
 * factor from the last five minutes, segregation of duty, every required approval present
 * and not superseded, no open grievance, and the rail accepting it. This screen's job is
 * to show the approver each of those *before* they press the button, so a refusal is
 * something they anticipated rather than a 409 they have to interpret.
 *
 * Two rules specific to money:
 *
 * **The household is a reference, never a name.** The approver does not need it and does
 * not get it. The queries behind this screen never select one, which is a stronger
 * guarantee than redacting it here would be.
 *
 * **The calculation is a derivation, not a total.** Schedule version, formula, each input,
 * each step, caps applied, final amount — expanded by default. An approver who is shown
 * only a number is being asked to rubber-stamp; an approver who can follow the arithmetic
 * can catch the schedule version being wrong, which is the error that actually happens.
 */

import {
  Badge,
  Button,
  EmptyState,
  Input,
  LKRAmount,
  ReferenceCode,
  RelativeTime,
  Select,
  Skeleton,
  cn,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import {
  useAnomalies,
  useEntitlement,
  useGrievances,
  useInvalidateGates,
} from '../lib/queries';
import { disbursementSchema, flagContext, isOpenAnomaly, isOpenGrievance } from '../lib/schemas';
import { stepUp } from '../lib/auth-actions';
import type { PrincipalSummary } from '../lib/session';
import { ErrorPanel } from './degraded';

const TOTP_LENGTH = 6;

/** The rails `ledger-svc` accepts. Every one is a mock in this phase. */
const PAYMENT_RAILS = ['BANK_TRANSFER', 'MOBILE_MONEY', 'POST_OFFICE'] as const;

export interface DisbursementGateProps {
  readonly entitlementId: string;
  readonly principal: PrincipalSummary | null;
}

export function DisbursementGate({ entitlementId, principal }: DisbursementGateProps) {
  const t = useTranslations('disbursement');
  const errors = useTranslations('errors');

  const entitlement = useEntitlement(entitlementId);
  const grievances = useGrievances(entitlementId);
  const anomalies = useAnomalies(entitlement.data?.gn_division_code);
  const invalidate = useInvalidateGates();

  const [totp, setTotp] = useState('');
  const [rail, setRail] = useState<string>(PAYMENT_RAILS[0]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [released, setReleased] = useState(false);
  const totpRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (entitlement.data) totpRef.current?.focus();
  }, [entitlement.data]);

  const totpComplete = /^\d{6}$/.test(totp);
  const openGrievances = (grievances.data ?? []).filter(isOpenGrievance);
  // Open flags whose subject is this entitlement, or the division it sits in. A flag on
  // the division is relevant to this approver: it is the pattern their next few decisions
  // are part of, and ADR-009 says the approver sees it.
  const relevantAnomalies = (anomalies.data ?? []).filter(
    (anomaly) => isOpenAnomaly(anomaly) && anomaly.subject_id !== '',
  );

  /**
   * Segregation of duty, computed from the approval records.
   *
   * The service decides this too, and its answer is the one that counts. Showing it here
   * turns an unexplained 409 into a line the approver reads before they start.
   */
  const conflictingRole = (() => {
    if (!principal || !entitlement.data) return null;
    const mine = entitlement.data.approvals.find(
      (approval) => approval.approver_id === principal.id,
    );
    return mine?.level ?? null;
  })();

  const blocked = openGrievances.length > 0 || conflictingRole !== null;

  async function release(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      const stepped = await stepUp(totp);
      if (!stepped.ok) {
        setFailure(new Error(stepped.message ?? errors('stepUpRequired')));
        return;
      }
      await gatewayFetch('disbursements', {
        method: 'POST',
        body: { entitlement_id: entitlementId, payment_rail: rail, acknowledged: true },
        // Keyed on the entitlement, so a double-tap or a retry after a dropped
        // connection replays the stored response instead of paying twice.
        idempotencyKey: `release-${entitlementId}`,
        schema: disbursementSchema,
      });
      setTotp('');
      setReleased(true);
      await Promise.all([entitlement.refetch(), invalidate()]);
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  if (entitlement.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-20" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (entitlement.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={entitlement.error} />
      </div>
    );
  }

  const record = entitlement.data;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        <Badge tone={blocked ? 'neutral' : 'pending'}>{record.status}</Badge>
      </header>

      <section className="grid gap-4 rounded-[var(--radius-default)] border border-[var(--divider)] p-4 sm:grid-cols-3">
        <Fact label={t('household')} hint={t('householdRefOnly')}>
          <ReferenceCode code={record.household_id.slice(0, 8)} />
        </Fact>
        <Fact label={t('division')}>
          <span data-sarana-datum="" className="font-mono text-sm">
            {record.gn_division_code}
          </span>
        </Fact>
        <Fact label={t('finalAmount')}>
          <LKRAmount cents={record.calculated_lkr_cents} className="text-lg font-semibold" />
        </Fact>
      </section>

      {/* Blocking conditions first. An approver should meet the reason they cannot
          proceed before they read the arithmetic. */}
      {openGrievances.length > 0 ? (
        <Blocker title={t('grievanceOpen')} body={t('grievanceExplanation')}>
          <ul className="mt-2 flex flex-col gap-1">
            {openGrievances.map((grievance) => (
              <li key={grievance.id} className="text-xs">
                <ReferenceCode code={grievance.public_ref ?? grievance.id.slice(0, 8)} />{' '}
                <span className="opacity-80">{grievance.status}</span>
              </li>
            ))}
          </ul>
        </Blocker>
      ) : null}

      {conflictingRole ? (
        <Blocker
          title={t('segregation')}
          body={t('segregationBlocked', { role: conflictingRole })}
        />
      ) : (
        <p className="flex items-center gap-2 text-xs text-[var(--verified)]">
          <svg viewBox="0 0 12 12" className="size-3" aria-hidden="true">
            <path
              d="M2.5 6.5 5 9l4.5-5.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {t('segregationOk')}
        </p>
      )}

      {relevantAnomalies.length > 0 ? (
        <section
          className={cn(
            'rounded-[var(--radius-default)] border px-4 py-3',
            'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]',
          )}
        >
          <p className="text-sm font-medium">{t('anomalyFlag')}</p>
          <p className="mt-1 text-xs opacity-90">{t('anomalyExplanation')}</p>
          {relevantAnomalies.map((anomaly) => {
            const context = flagContext(anomaly);
            return (
              <div key={anomaly.id} className="mt-2 text-xs">
                <span data-sarana-datum="" className="font-mono">
                  {anomaly.detector}
                </span>
                {context.pattern_summary ? (
                  <p className="mt-1 opacity-90">{context.pattern_summary}</p>
                ) : null}
                {/* The ordinary reasons this pattern might be here, before anything else.
                    A flag shown without them reads as an accusation. */}
                {context.innocent_explanations.length > 0 ? (
                  <ul className="ml-4 mt-1 list-disc opacity-90">
                    {context.innocent_explanations.map((explanation) => (
                      <li key={explanation}>{explanation}</li>
                    ))}
                  </ul>
                ) : null}
                {context.what_would_resolve_it.length > 0 ? (
                  <ul className="ml-4 mt-1 list-disc opacity-90">
                    {context.what_would_resolve_it.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            );
          })}
        </section>
      ) : null}

      <CalculationTrace
        trace={record.calculation_trace}
        scheduleVersion={record.cost_schedule_version}
        amountCents={record.calculated_lkr_cents}
      />

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('approvals')}</h2>
        {record.approvals.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">—</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {record.approvals.map((approval, index) => (
              <li
                key={`${approval.approver_id ?? index}-${approval.level ?? index}`}
                className="flex flex-wrap items-baseline gap-3 text-xs"
              >
                <Badge tone="verified">{approval.level ?? '—'}</Badge>
                <span data-sarana-datum="" className="font-mono">
                  {approval.approver_id?.slice(0, 8) ?? '—'}
                </span>
                {approval.decided_at ? <RelativeTime value={approval.decided_at} /> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {failure ? <ErrorPanel error={failure} /> : null}

      {released ? (
        <EmptyState
          title={t('release')}
          description={t('simulated')}
          action={
            <Button asChild variant="secondary">
              <Link href="/disbursements">{t('queueTitle')}</Link>
            </Button>
          }
        />
      ) : (
        <section className="flex flex-col gap-3 rounded-[var(--radius-default)] border border-[var(--divider)] p-4">
          <Select
            label={t('paymentRail')}
            value={rail}
            onValueChange={setRail}
            options={PAYMENT_RAILS.map((value) => ({ value, label: value }))}
          />
          <Input
            ref={totpRef}
            label={t('title')}
            description={t('releaseConfirm')}
            value={totp}
            onChange={(event) =>
              setTotp(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))
            }
            inputMode="numeric"
            autoComplete="one-time-code"
            datum
            maxLength={TOTP_LENGTH}
          />
          <Button
            type="button"
            variant="primary"
            size="lg"
            // Disabled when the service would refuse anyway. Letting the click through to
            // collect a 409 would teach approvers that refusals are noise.
            disabled={!totpComplete || blocked || busy}
            busy={busy}
            busyLabel={t('release')}
            onClick={release}
          >
            {t('release')}
          </Button>
          <p className="text-2xs text-[var(--text-muted)]">{t('simulated')}</p>
        </section>
      )}
    </div>
  );
}

function Fact({
  label,
  hint,
  children,
}: {
  readonly label: string;
  readonly hint?: string;
  readonly children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
      {children}
      {hint ? <span className="text-2xs text-[var(--text-muted)]">{hint}</span> : null}
    </div>
  );
}

function Blocker({
  title,
  body,
  children,
}: {
  readonly title: string;
  readonly body: string;
  readonly children?: React.ReactNode;
}) {
  return (
    <section
      role="alert"
      className={cn(
        'rounded-[var(--radius-default)] border px-4 py-3',
        'border-[var(--sev-3-border)] bg-[var(--sev-3-bg)] text-[var(--sev-3-fg)]',
      )}
    >
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs opacity-90">{body}</p>
      {children}
    </section>
  );
}

/**
 * The calculation, rendered as a readable derivation.
 *
 * `calculation_trace` is whatever `ledger-svc` recorded, so this walks it structurally
 * rather than assuming a shape. A trace with an unexpected key is rendered rather than
 * dropped: the one thing this panel must never do is silently omit a step, because the
 * step it omits is the one the approver needed.
 */
function CalculationTrace({
  trace,
  scheduleVersion,
  amountCents,
}: {
  readonly trace: Record<string, unknown>;
  readonly scheduleVersion: string;
  readonly amountCents: number;
}) {
  const t = useTranslations('disbursement');
  const entries = Object.entries(trace);

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{t('calculation')}</h2>
      <div className="rounded-[var(--radius-default)] border border-[var(--divider)] bg-[var(--surface-card)] p-4">
        <dl className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
              {t('scheduleVersion')}
            </dt>
            <dd data-sarana-datum="" className="font-mono text-sm">
              {scheduleVersion}
            </dd>
          </div>

          {entries.map(([key, value]) => (
            <div key={key} className="flex flex-wrap items-baseline gap-2">
              <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
                {key}
              </dt>
              <dd data-sarana-datum="" className="font-mono text-xs">
                {renderTraceValue(value)}
              </dd>
            </div>
          ))}

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
    </section>
  );
}

function renderTraceValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
