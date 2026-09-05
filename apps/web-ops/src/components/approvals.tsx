'use client';

/**
 * `/approvals` — entitlements waiting for a DS or District signature.
 *
 * This is the step before the money gate: an entitlement is calculated, then approved at
 * one or two levels, and only then can it be released. The screen shows what each row is
 * still waiting for rather than a generic "pending", because "needs District" and "needs
 * DS" send the work to different people.
 *
 * **The level is derived from the amount and shown, never chosen freely.** Above the
 * threshold an entitlement needs both signatures; at or below it needs one. The console
 * computes that only to say which button to offer — `ledger-svc` decides what is required
 * and refuses if this is ever wrong.
 *
 * **Approving is not the same act as releasing.** An approver here is signing that the
 * calculation is right for this household; the releaser is a different person confirming
 * the money should move now. `ledger-svc` refuses a release by whoever approved it, and
 * the money gate shows that line before the button.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  Input,
  LKRAmount,
  ReferenceCode,
  RelativeTime,
  Skeleton,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Link } from '../i18n/routing';
import { gatewayFetch } from '../lib/gateway-client';
import { useEntitlementQueue, useInvalidateGates } from '../lib/queries';
import { outstandingLevels, type ApprovalLevel, type EntitlementSummary } from '../lib/schemas';
import { stepUp } from '../lib/auth-actions';
import { ErrorPanel } from './degraded';

const TOTP_LENGTH = 6;

export function ApprovalQueue() {
  const t = useTranslations('approvals');
  const disbursement = useTranslations('disbursement');
  const cop = useTranslations('cop');

  // Everything not yet released. The rows that already carry every signature are the
  // release queue's work, and they are marked here rather than hidden so an approver can
  // see their own signature landed.
  const queue = useEntitlementQueue(false);
  const [selected, setSelected] = useState<EntitlementSummary | null>(null);

  if (queue.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (queue.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={queue.error} />
      </div>
    );
  }

  const rows = (queue.data ?? []).filter((row) => !row.released);

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">{t('title')}</h1>
        <p className="text-xs text-[var(--text-muted)]">{t('subtitle')}</p>
      </header>

      <DataTable<EntitlementSummary>
        caption={t('title')}
        rows={rows}
        rowKey={(row) => row.id}
        height="calc(100vh - 22rem)"
        onRowActivate={setSelected}
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'ref',
            header: cop('reference'),
            width: '14rem',
            cell: (row) => <ReferenceCode code={row.assessment_ref} />,
          },
          {
            key: 'division',
            header: cop('division'),
            width: '11rem',
            cell: (row) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {row.gn_division_code}
              </span>
            ),
          },
          {
            key: 'category',
            header: disbursement('category'),
            width: '10rem',
            cell: (row) => <Badge tone="neutral">{row.category}</Badge>,
          },
          {
            key: 'amount',
            header: disbursement('finalAmount'),
            width: '13rem',
            numeric: true,
            cell: (row) => <LKRAmount cents={row.calculated_lkr_cents} />,
          },
          {
            key: 'waiting',
            header: t('waitingFor'),
            width: '14rem',
            // What this row is waiting for, not a generic "pending". "Needs District" and
            // "needs DS" send the work to different people.
            cell: (row) => {
              const outstanding = outstandingLevels(row);
              return outstanding.length === 0 ? (
                <Badge tone="verified">{t('fullyApproved')}</Badge>
              ) : (
                <span className="flex flex-wrap gap-1">
                  {outstanding.map((level) => (
                    <Badge key={level} tone="pending">
                      {t('needs', { level })}
                    </Badge>
                  ))}
                </span>
              );
            },
          },
          {
            key: 'calculated',
            header: t('calculated'),
            cell: (row) => <RelativeTime value={row.calculated_at} />,
          },
        ]}
      />

      {selected ? (
        <ApprovalPanel
          row={selected}
          onDone={() => {
            setSelected(null);
            void queue.refetch();
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * Sign one level on one entitlement.
 *
 * A second factor, like every other consequential action on this console. An approval is
 * not money moving, but it is the signature the money gate then relies on, and an
 * unattended workstation is the realistic attack on a platform like this.
 */
function ApprovalPanel({
  row,
  onDone,
}: {
  readonly row: EntitlementSummary;
  readonly onDone: () => void;
}) {
  const t = useTranslations('approvals');
  const disbursement = useTranslations('disbursement');
  const errors = useTranslations('errors');
  const invalidate = useInvalidateGates();

  const outstanding = outstandingLevels(row);
  const [level, setLevel] = useState<ApprovalLevel>(outstanding[0] ?? 'DS');
  const [totp, setTotp] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);

  const totpComplete = /^\d{6}$/.test(totp);

  async function approve(): Promise<void> {
    setBusy(true);
    setFailure(null);
    try {
      const stepped = await stepUp(totp);
      if (!stepped.ok) {
        setFailure(new Error(stepped.message ?? errors('stepUpRequired')));
        return;
      }
      await gatewayFetch(`entitlements/${row.id}/approve`, {
        method: 'POST',
        body: { level, decision: 'APPROVED' },
        // Keyed on the entitlement and the level, so a double-tap replays rather than
        // recording a second signature at the same level.
        idempotencyKey: `approve-${row.id}-${level}`,
      });
      setTotp('');
      await invalidate();
      onDone();
    } catch (error) {
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex flex-col gap-3 rounded-[var(--radius-default)] border border-[var(--pending)] p-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-sm font-medium">{t('signTitle')}</h2>
        <ReferenceCode code={row.assessment_ref} />
        <LKRAmount cents={row.calculated_lkr_cents} className="ml-auto text-base font-semibold" />
      </header>

      <p className="text-xs text-[var(--text-muted)]">
        {disbursement('scheduleVersion')}:{' '}
        <span data-sarana-datum="" className="font-mono">
          {row.cost_schedule_version}
        </span>
      </p>

      {/* The full working is one click away, on the screen that is about to move the
          money. An approver signing without reading it is the failure a trace exists to
          prevent, so the link is prominent rather than a footnote. */}
      <Button asChild variant="secondary" size="sm" className="self-start">
        <Link href={`/disbursements/${row.id}`}>{disbursement('calculation')}</Link>
      </Button>

      {outstanding.length === 0 ? (
        <p className="text-xs text-[var(--verified)]">{t('fullyApproved')}</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {outstanding.map((candidate) => (
              <Button
                key={candidate}
                size="sm"
                variant={candidate === level ? 'primary' : 'secondary'}
                onClick={() => setLevel(candidate)}
              >
                {t('needs', { level: candidate })}
              </Button>
            ))}
          </div>

          <Input
            label={t('totpLabel')}
            description={t('totpHint')}
            inputMode="numeric"
            autoComplete="one-time-code"
            datum
            maxLength={TOTP_LENGTH}
            value={totp}
            onChange={(event) =>
              setTotp(event.target.value.replace(/\D/g, '').slice(0, TOTP_LENGTH))
            }
          />

          {failure ? <ErrorPanel error={failure} /> : null}

          <Button
            variant="primary"
            size="lg"
            disabled={!totpComplete || busy}
            busy={busy}
            busyLabel={t('sign', { level })}
            onClick={approve}
            className="self-start"
          >
            {t('sign', { level })}
          </Button>
          <p className="text-2xs text-[var(--text-muted)]">{t('notARelease')}</p>
        </>
      )}
    </section>
  );
}
