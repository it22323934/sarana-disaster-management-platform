'use client';

/**
 * `/disbursements` — the release queue, and the endpoint it does not have.
 *
 * `ledger-svc` exposes `GET /entitlements/{id}` but **no list endpoint**, so there is no
 * way to ask "which entitlements are approved and waiting to be released". The gate
 * screen itself works — it takes an entitlement id — but the queue in front of it cannot
 * be assembled from the API as it stands.
 *
 * Rather than fake it, this screen does three honest things:
 *
 *   1. says the list is not available and why, so nobody concludes the queue is empty;
 *   2. offers direct entry by entitlement id, which is how approvers are told about work
 *      today — out of band, from an assessment reference;
 *   3. shows what has recently been released, from `GET /disbursements`, so an approver
 *      can confirm their own release landed.
 *
 * An empty list here would be the most dangerous screen in the console: it would tell a
 * district approver there is no money waiting when there might be a hundred households.
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
import { useDisbursements } from '../lib/queries';
import type { Disbursement } from '../lib/schemas';
import { DegradedBanner, ErrorPanel } from './degraded';

export function ReleaseQueue() {
  const t = useTranslations('disbursement');
  const common = useTranslations('common');
  const router = useRouter();
  const released = useDisbursements();
  const [entitlementId, setEntitlementId] = useState('');

  const rows = (released.data ?? []) as Disbursement[];

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('queueTitle')}</h1>

      {/* The gap, stated. Not an empty state — an empty state would be a claim that
          nothing is waiting, and nothing here knows that. */}
      <DegradedBanner kind="list" />

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
