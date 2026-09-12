'use client';

/**
 * The dispatch queue: everything waiting for a human decision, oldest first.
 *
 * Oldest first and not sortable. Every other list on this console can be reordered; this
 * one cannot, because the order *is* the policy. A dispatcher who sorts by severity works
 * the loud items and leaves an old class-2 plan sitting for an hour, and the whole point
 * of the gate is that nothing sits.
 */

import { Badge, Button, DataTable, EmptyState, ReferenceCode, RelativeTime } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import { usePendingPlans } from '../lib/queries';
import type { DispatchPlan } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function DispatchQueue() {
  const t = useTranslations('dispatch');
  const common = useTranslations('common');
  const plans = usePendingPlans();

  if (plans.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={plans.error} />
      </div>
    );
  }

  const rows = plans.data ?? [];

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('queueTitle')}</h1>

      <DataTable<DispatchPlan>
        caption={t('queueTitle')}
        rows={rows}
        rowKey={(plan) => plan.id}
        height="calc(100vh - 18rem)"
        empty={
          <EmptyState title={t('queueEmpty')} description={t('queueEmptyHint')} />
        }
        columns={[
          {
            key: 'ref',
            header: t('status'),
            width: '10rem',
            cell: (plan) => <ReferenceCode code={plan.id.slice(0, 8)} />,
          },
          {
            key: 'status',
            header: t('status'),
            width: '11rem',
            cell: (plan) => <Badge tone="pending">{plan.status}</Badge>,
          },
          {
            key: 'incidents',
            header: t('incidents'),
            width: '7rem',
            numeric: true,
            cell: (plan) => (
              <span data-sarana-datum="" className="font-mono">
                {plan.incident_ids.length}
              </span>
            ),
          },
          {
            key: 'responders',
            header: t('responders'),
            width: '8rem',
            numeric: true,
            cell: (plan) => (
              <span data-sarana-datum="" className="font-mono">
                {plan.responder_ids.length}
              </span>
            ),
          },
          {
            key: 'waiting',
            header: t('proposedBy'),
            cell: (plan) => <RelativeTime value={plan.proposed_at} />,
          },
          {
            key: 'open',
            header: common('review'),
            width: '9rem',
            cell: (plan) => (
              <Button asChild size="sm" variant="primary">
                <Link href={`/ops/dispatch/${plan.id}`}>{common('review')}</Link>
              </Button>
            ),
          },
        ]}
      />
    </div>
  );
}
