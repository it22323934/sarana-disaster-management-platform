'use client';

/**
 * The incident list and one incident's detail.
 *
 * The thing this screen has to get right is `location_confidence`. Every point on this
 * platform carries an accuracy and a source, and a point with low confidence **is not
 * trusted for dispatch** — that is a rule from the conventions, not a display preference.
 * So a low-confidence incident is marked, and the mark says what follows from it rather
 * than showing a bare number an operator learns to scroll past.
 */

import {
  Badge,
  ConfidenceMeter,
  DataTable,
  EmptyState,
  ReferenceCode,
  RelativeTime,
  SeverityPill,
  Skeleton,
  cn,
} from '@sarana/ui';
import type { ConfidenceBand, SeverityLevel } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { useAuditTrail, useIncident, useIncidents } from '../lib/queries';
import type { Incident } from '../lib/schemas';
import { AuditTrail } from '@sarana/ui';
import { ErrorPanel } from './degraded';
import { DedupLinks, LinkedReports } from './linked-reports';

/**
 * Below this, a location is not trusted for dispatch.
 *
 * Matches the triage agent's own threshold. If the two ever disagree, the console is the
 * one that is wrong: the agent's copy decides whether a plan can be built at all.
 */
const DISPATCHABLE_CONFIDENCE = 0.6;

function bandFor(confidence: number): ConfidenceBand {
  if (confidence >= 0.8) return 'high';
  if (confidence >= DISPATCHABLE_CONFIDENCE) return 'medium';
  return 'low';
}

export function IncidentList() {
  const t = useTranslations('incidents');
  const cop = useTranslations('cop');
  const incidents = useIncidents();

  if (incidents.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={incidents.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      <DataTable<Incident>
        caption={t('title')}
        rows={incidents.data ?? []}
        rowKey={(incident) => incident.id}
        height="calc(100vh - 16rem)"
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'ref',
            header: cop('reference'),
            width: '15rem',
            cell: (incident) => <ReferenceCode code={incident.public_ref} />,
          },
          {
            key: 'severity',
            header: cop('severity'),
            width: '11rem',
            cell: (incident) => (
              <SeverityPill level={incident.severity as SeverityLevel} locale="en" />
            ),
          },
          {
            key: 'division',
            header: cop('division'),
            width: '12rem',
            cell: (incident) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {incident.gn_division_code}
              </span>
            ),
          },
          {
            key: 'people',
            header: cop('peopleAtRisk'),
            width: '9rem',
            numeric: true,
            cell: (incident) => (
              <span data-sarana-datum="" className="font-mono">
                {incident.people_at_risk}
              </span>
            ),
          },
          {
            key: 'status',
            header: t('status'),
            width: '10rem',
            cell: (incident) => <Badge tone="neutral">{incident.status}</Badge>,
          },
          {
            key: 'reported',
            header: t('reported'),
            cell: (incident) => <RelativeTime value={incident.first_reported_at} />,
          },
        ]}
      />
    </div>
  );
}

export interface IncidentDetailProps {
  readonly incidentId: string;
}

export function IncidentDetail({ incidentId }: IncidentDetailProps) {
  const t = useTranslations('incidents');
  const cop = useTranslations('cop');
  const incident = useIncident(incidentId);
  const audit = useAuditTrail('incident', incidentId);

  if (incident.isPending) {
    return (
      <div className="flex flex-col gap-4 p-6">
        <Skeleton className="h-20" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  if (incident.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={incident.error} />
      </div>
    );
  }

  const record = incident.data;
  const confidence = record.location_confidence;
  const undispatchable = confidence !== null && confidence < DISPATCHABLE_CONFIDENCE;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">{t('detailTitle')}</h1>
        <SeverityPill level={record.severity as SeverityLevel} locale="en" />
        <ReferenceCode code={record.public_ref} />
        <Badge tone="neutral">{record.status}</Badge>
      </header>

      <dl className="grid gap-4 rounded-[var(--radius-default)] border border-[var(--divider)] p-4 sm:grid-cols-3">
        <Field label={cop('division')} value={record.gn_division_code} datum />
        <Field label={t('type')} value={record.subtype ?? record.type} />
        <Field label={cop('peopleAtRisk')} value={String(record.people_at_risk)} datum />
        <div className="flex flex-col gap-1">
          <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">
            {t('reported')}
          </dt>
          <dd>
            <RelativeTime value={record.first_reported_at} />
          </dd>
        </div>
      </dl>

      {confidence === null ? null : (
        <section
          className={cn(
            'flex flex-col gap-2 rounded-[var(--radius-default)] border p-4',
            undispatchable
              ? 'border-[var(--sev-2-border)] bg-[var(--sev-2-bg)] text-[var(--sev-2-fg)]'
              : 'border-[var(--divider)]',
          )}
        >
          <h2 className="text-sm font-medium">{t('locationConfidence')}</h2>
          {/* The consequence, not the number alone. A confidence figure with nothing
              following from it teaches an operator to ignore it. */}
          <ConfidenceMeter
            value={confidence}
            band={bandFor(confidence)}
            bandLabel={undispatchable ? t('locationLow') : t('locationConfidence')}
            consequence={undispatchable ? t('locationLowHint') : t('locationConfidence')}
          />
        </section>
      )}

      {/* What was reported, before what the platform did about it. The order is the
          argument: an operator forming a view of this incident should read the words
          somebody used before reading the actions taken on their behalf. */}
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{cop('reports')}</h2>
        <LinkedReports reports={record.reports} failed={false} />
      </section>

      <DedupLinks links={record.dedup_links} />

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">{cop('auditTrail')}</h2>
        {audit.isError ? (
          // A failed audit read is not an empty audit trail. Nothing on screen would say
          // this incident has no history, which is a claim about the incident.
          <p className="text-xs text-[var(--sev-2-fg)]">{cop('auditUnavailable')}</p>
        ) : (audit.data ?? []).length === 0 ? (
          <p className="text-xs text-[var(--text-muted)]">{cop('auditEmpty')}</p>
        ) : (
          <AuditTrail
            label={cop('auditTrail')}
            entries={(audit.data ?? []).map((entry) => ({
              id: entry.id,
              at: <RelativeTime value={entry.occurred_at} />,
              // An agent is named; a person is a type. No personal name appears because
              // the query never selects one.
              actor: entry.agent_name ?? entry.actor_type,
              action: entry.action,
              correlationId: entry.correlation_id,
            }))}
          />
        )}
      </section>
    </div>
  );
}

function Field({
  label,
  value,
  datum = false,
}: {
  readonly label: string;
  readonly value: string;
  readonly datum?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-2xs uppercase tracking-wide text-[var(--text-muted)]">{label}</dt>
      <dd
        {...(datum ? { 'data-sarana-datum': '' } : {})}
        className={datum ? 'font-mono text-sm' : 'text-sm'}
      >
        {value}
      </dd>
    </div>
  );
}
