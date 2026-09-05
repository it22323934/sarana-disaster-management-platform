'use client';

/**
 * `/disbursements` — the release queue.
 *
 * `GET /entitlements?awaiting_release=true` is what fills it, and the service applies the
 * approval rule rather than the console: readiness is decided by `domain/approval.py`,
 * which is the same module the disbursement gate refuses with. A second copy of that rule
 * here would drift, and the way drift presents is a queue offering an approver work the
 * gate then rejects — which teaches approvers that refusals are noise.
 *
 * Oldest first, from the server. The household that has waited longest is the one to reach
 * first, and a newest-first list buries them under everything written since.
 *
 * Direct entry by reference stays, because an approver is still often told about a
 * specific entitlement out of band. What has recently been released stays too, so an
 * approver can confirm their own release landed.
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
} from '@sarana/ui';
import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { useRouter } from '../i18n/routing';
import { useDisbursements, useEntitlementQueue } from '../lib/queries';
import type { Disbursement, EntitlementSummary } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function ReleaseQueue() {
  const t = useTranslations('disbursement');
  const common = useTranslations('common');
  const router = useRouter();
  const released = useDisbursements();
  const waiting = useEntitlementQueue(true);
  const [entitlementId, setEntitlementId] = useState('');

  const rows = (released.data ?? []) as Disbursement[];

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('queueTitle')}</h1>

      {waiting.isError ? (
        <ErrorPanel error={waiting.error} />
      ) : (
        <DataTable<EntitlementSummary>
          caption={t('queueTitle')}
          rows={waiting.data ?? []}
          rowKey={(row) => row.id}
          height="24rem"
          onRowActivate={(row) => router.push(`/disbursements/${row.id}`)}
          empty={<EmptyState title={t('queueEmpty')} description={t('queueEmptyHint')} />}
          columns={[
            {
              key: 'ref',
              header: t('household'),
              width: '14rem',
              cell: (row) => <ReferenceCode code={row.assessment_ref} />,
            },
            {
              key: 'division',
              header: t('division'),
              width: '11rem',
              cell: (row) => (
                <span data-sarana-datum="" className="font-mono text-xs">
                  {row.gn_division_code}
                </span>
              ),
            },
            {
              key: 'amount',
              header: t('finalAmount'),
              width: '13rem',
              numeric: true,
              cell: (row) => <LKRAmount cents={row.calculated_lkr_cents} />,
            },
            {
              key: 'approvals',
              header: t('approvals'),
              width: '12rem',
              // The levels that signed, not a count. Two signatures at one level are not
              // two levels, and the gate checks levels.
              cell: (row) => (
                <span className="flex flex-wrap gap-1">
                  {row.approved_levels.map((level) => (
                    <Badge key={level} tone="verified">
                      {level}
                    </Badge>
                  ))}
                </span>
              ),
            },
            {
              key: 'waiting',
              header: t('approvalAt'),
              cell: (row) => <RelativeTime value={row.calculated_at} />,
            },
          ]}
        />
      )}

      <form
        className="flex flex-wrap items-end gap-3 rounded-[var(--radius-default)] border border-[var(--divider)] p-4"
        onSubmit={(event) => {
          event.preventDefault();
          const id = entitlementId.trim();
          if (id.length > 0) router.push(`/disbursements/${id}`);
        }}
      >
        <Input
          label={t('household')}
          description={t('householdRefOnly')}
          value={entitlementId}
          onChange={(event) => setEntitlementId(event.target.value)}
          datum
          className="min-w-[22rem]"
        />
        <Button type="submit" variant="primary" disabled={entitlementId.trim().length === 0}>
          {common('review')}
        </Button>
      </form>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('release')}</h2>
        {released.isError ? (
          <ErrorPanel error={released.error} />
        ) : (
          <DataTable<Disbursement>
            caption={t('release')}
            rows={rows}
            rowKey={(row) => row.id}
            height="26rem"
            empty={<EmptyState title={t('queueEmpty')} description={t('queueEmptyHint')} />}
            columns={[
              {
                key: 'seq',
                header: '#',
                width: '6rem',
                numeric: true,
                cell: (row) => (
                  <span data-sarana-datum="" className="font-mono">
                    {row.seq}
                  </span>
                ),
              },
              {
                key: 'ref',
                header: t('household'),
                width: '12rem',
                cell: (row) => <ReferenceCode code={row.entitlement_id.slice(0, 8)} />,
              },
              {
                key: 'amount',
                header: t('finalAmount'),
                width: '12rem',
                numeric: true,
                cell: (row) => <LKRAmount cents={row.amount_lkr_cents} />,
              },
              {
                key: 'rail',
                header: t('paymentRail'),
                width: '12rem',
                cell: (row) => (
                  <span className="flex items-center gap-2">
                    <span className="text-xs">{row.payment_rail}</span>
                    {/* Every rail in this phase is a mock, and the badge says so on every
                        row rather than once at the top where it stops being read. */}
                    {row.simulated ? <Badge tone="neutral">MOCK</Badge> : null}
                  </span>
                ),
              },
              {
                key: 'at',
                header: t('approvalAt'),
                cell: (row) => <RelativeTime value={row.released_at} />,
              },
            ]}
          />
        )}
      </section>
    </div>
  );
}
