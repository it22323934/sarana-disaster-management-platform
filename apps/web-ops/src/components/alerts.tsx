'use client';

/**
 * Alerts, and the screen that matters more than the list: the delivery gaps panel.
 *
 * The gaps panel is what turns "we sent the warning" into "these 14 divisions probably
 * did not get it, send a vehicle". It is one click from the alert, never buried, and the
 * server orders it worst-first — the console does not re-sort, because that order is the
 * instruction.
 *
 * **No delivery figure appears without its denominator.** Not once, anywhere on this
 * screen. "82% confirmed" over an unstated base is how a district gets reported as covered
 * when the base was four synthetic people. Every count is rendered as `n of m`, and the
 * server's own `summary` sentence is rendered verbatim rather than recomputed here — a
 * second statement of the same fact is a second thing that can drift.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  StatCard,
  cn,
} from '@sarana/ui';
import type { SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import { useAlerts, useDelivery, useDeliveryGaps } from '../lib/queries';
import type { Alert, Gap } from '../lib/schemas';
import { ErrorPanel } from './degraded';
import { GapMap } from './gap-map';

/**
 * Statuses from which a dispatch is still possible.
 *
 * Kept beside the list rather than imported from the dispatch screen, so this module does
 * not pull a client component's whole dependency tree in for one array.
 */
const DISPATCHABLE_STATUSES = ['DRAFT', 'PENDING_SIGNOFF', 'APPROVED'];

export function AlertList() {
  const t = useTranslations('alerts');
  const common = useTranslations('common');
  const alerts = useAlerts();

  if (alerts.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={alerts.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      <DataTable<Alert>
        caption={t('title')}
        rows={alerts.data ?? []}
        rowKey={(alert) => alert.id}
        height="calc(100vh - 16rem)"
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'cap',
            header: t('capId'),
            width: '18rem',
            cell: (alert) => <ReferenceCode code={alert.cap_identifier} />,
          },
          {
            key: 'severity',
            header: t('status'),
            width: '11rem',
            cell: (alert) =>
              alert.severity === null ? (
                <Badge tone="neutral">{alert.status}</Badge>
              ) : (
                <SeverityPill level={alert.severity as SeverityLevel} locale="en" />
              ),
          },
          {
            key: 'status',
            header: t('status'),
            width: '12rem',
            cell: (alert) => (
              <span className="flex items-center gap-2">
                <Badge tone={alert.requires_human_signoff ? 'pending' : 'neutral'}>
                  {alert.status}
                </Badge>
                {alert.requires_human_signoff ? (
                  <span className="text-2xs text-[var(--pending)]">{t('needsSignoff')}</span>
                ) : null}
              </span>
            ),
          },
          {
            key: 'effective',
            header: t('effective'),
            cell: (alert) =>
              alert.effective_at ? <RelativeTime value={alert.effective_at} /> : '—',
          },
          {
            key: 'actions',
            header: t('delivery'),
            width: '16rem',
            // Two destinations, and which one is useful depends on the row. A draft goes
            // to the dry run; a dispatched alert goes to its delivery. Offering both on
            // every row would put "send" beside an alert that has already gone out.
            cell: (alert) => (
              <span className="flex flex-wrap gap-2">
                {DISPATCHABLE_STATUSES.includes(alert.status) ? (
                  <Button asChild size="sm" variant="primary">
                    <Link href={`/ops/alerts/${alert.id}`}>{t('openDraft')}</Link>
                  </Button>
                ) : null}
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/ops/alerts/${alert.id}/delivery`}>{common('review')}</Link>
                </Button>
              </span>
            ),
          },
        ]}
      />
    </div>
  );
}

export interface DeliveryPanelProps {
  readonly alertId: string;
}

export function DeliveryPanel({ alertId }: DeliveryPanelProps) {
  const t = useTranslations('alerts');
  const delivery = useDelivery(alertId);
  const gaps = useDeliveryGaps(alertId);

  if (delivery.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (delivery.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={delivery.error} />
      </div>
    );
  }

  const counts = delivery.data;
  const targeted = counts.targeted;

  return (
    <div className="flex flex-col gap-6 p-6">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">{t('deliveryTitle')}</h1>
        <ReferenceCode code={alertId.slice(0, 8)} kind={t('capId')} />
      </header>

      {/* The server's own sentence, verbatim. It is guaranteed never to be a bare
          percentage, and recomputing one here would be a second thing that can drift. */}
      <p className="text-sm text-[var(--text-primary)]">{counts.summary}</p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Count label={t('targeted')} value={targeted} of={targeted} asOf={counts.summary} />
        <Count label={t('confirmed')} value={counts.confirmed} of={targeted} asOf={counts.summary} />
        <Count
          label={t('unconfirmed')}
          value={counts.unconfirmed}
          of={targeted}
          asOf={counts.summary}
        />
        <Count label={t('failed')} value={counts.failed} of={targeted} asOf={counts.summary} />
        <Count
          label={t('noChannel')}
          value={counts.no_channel}
          of={targeted}
          asOf={counts.summary}
        />
      </div>

      <p className="text-2xs text-[var(--text-muted)]">{t('noDenominator')}</p>

      <div className="grid gap-6 lg:grid-cols-2">
        <Breakdown
          title={t('byChannel')}
          rows={Object.entries(counts.by_channel).map(([channel, states]) => ({
            label: channel,
            value: Object.entries(states)
              .map(([state, count]) => `${state} ${count}`)
              .join(' · '),
          }))}
        />
        <Breakdown
          title={t('byLanguage')}
          rows={Object.entries(counts.by_language).map(([language, count]) => ({
            label: language,
            value: `${count} ${t('targeted').toLowerCase()}`,
          }))}
        />
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{t('gaps')}</h2>
        <p className="text-xs text-[var(--text-muted)]">{t('gapsHint')}</p>
        {/* Shaded by confirmed fraction on a single-hue sequential ramp, never the
            severity ramp: a division whose receipts have not arrived is not a worse
            hazard than the one next to it, and borrowing those five colours would say so.
            The table below is the authority and stays in the server's order. */}
        <GapMap gaps={gaps.data ?? []} />
        {gaps.isError ? (
          <ErrorPanel error={gaps.error} />
        ) : (
          <DataTable<Gap>
            caption={t('gaps')}
            // Not re-sorted. The server returns worst-first and that order is the
            // instruction: it says which division to send a vehicle to first.
            rows={gaps.data ?? []}
            rowKey={(gap) => gap.gn_division_code}
            height="24rem"
            empty={<EmptyState title={t('gapsNone')} description={t('gapsNoneHint')} />}
            columns={[
              {
                key: 'division',
                header: t('targeted'),
                width: '14rem',
                cell: (gap) => (
                  <span data-sarana-datum="" className="font-mono text-sm">
                    {gap.gn_division_code}
                  </span>
                ),
              },
              {
                key: 'confirmed',
                header: t('confirmed'),
                width: '12rem',
                numeric: true,
                // `n of m`, never a bare fraction.
                cell: (gap) => (
                  <span data-sarana-datum="" className="font-mono">
                    {gap.confirmed} / {gap.targeted}
                  </span>
                ),
              },
              {
                key: 'summary',
                header: t('gaps'),
                cell: (gap) => <span className="text-xs">{gap.summary}</span>,
              },
            ]}
          />
        )}
      </section>
    </div>
  );
}

/**
 * One delivery figure, and what it is a fraction of.
 *
 * `of` is required. There is no variant of this component that renders a count alone,
 * because the moment one exists it gets used on the busiest screen in the product.
 */
function Count({
  label,
  value,
  of,
  asOf,
}: {
  readonly label: string;
  readonly value: number;
  readonly of: number;
  readonly asOf: string;
}) {
  return (
    <StatCard
      label={label}
      value={
        <span className="flex items-baseline gap-1">
          <span>{value.toLocaleString('en-LK')}</span>
          <span className="text-sm font-normal opacity-70">
            / {of.toLocaleString('en-LK')}
          </span>
        </span>
      }
      asOf={asOf}
    />
  );
}

function Breakdown({
  title,
  rows,
}: {
  readonly title: string;
  readonly rows: ReadonlyArray<{ readonly label: string; readonly value: string }>;
}) {
  return (
    <section
      className={cn(
        'rounded-[var(--radius-default)] border border-[var(--divider)]',
        'bg-[var(--surface-card)] p-4',
      )}
    >
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-[var(--text-muted)]">—</p>
      ) : (
        <dl className="flex flex-col gap-1">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline justify-between gap-4 text-xs">
              <dt className="text-[var(--text-muted)]">{row.label}</dt>
              <dd data-sarana-datum="" className="font-mono">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
