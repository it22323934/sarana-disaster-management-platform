'use client';

/**
 * `/field/assessments` — the GN officer's web fallback.
 *
 * The mobile Field Companion is the real tool for this; a GN officer assesses damage
 * standing in front of a house, usually with no signal. This screen exists for the case
 * where the handset is dead, lost or never issued, and for a DS officer reviewing what
 * their division has submitted from a desk.
 *
 * It is read-only. Creating an assessment needs photographs with EXIF GPS, an offline
 * queue and a capability token issued before going into the field — all of which are the
 * mobile app's job and none of which a browser at a desk can honestly provide. A form here
 * that accepted an assessment without evidence would be a way of entering damage figures
 * nobody stood in front of.
 */

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  LKRAmount,
  ReferenceCode,
  RelativeTime,
} from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { Link } from '../i18n/routing';
import { useAssessments } from '../lib/queries';
import type { Assessment } from '../lib/schemas';
import { ErrorPanel } from './degraded';

export function AssessmentList() {
  const t = useTranslations('assessments');
  const disbursement = useTranslations('disbursement');
  const cop = useTranslations('cop');
  const assessments = useAssessments();

  if (assessments.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={assessments.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold">{t('title')}</h1>
          <p className="text-xs text-[var(--text-muted)]">{t('readOnly')}</p>
        </div>
        {/* Secondary, not primary. The mobile app is the way to file an assessment and
            this button leads to the weaker path; making it the loudest control on the
            screen would invite the desk to become the default. */}
        <Button asChild variant="secondary" size="sm" className="ml-auto">
          <Link href="/field/assessments/new">{t('newTitle')}</Link>
        </Button>
      </header>

      <DataTable<Assessment>
        caption={t('title')}
        rows={assessments.data ?? []}
        rowKey={(assessment) => assessment.id}
        height="calc(100vh - 18rem)"
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'ref',
            header: cop('reference'),
            width: '15rem',
            cell: (assessment) => <ReferenceCode code={assessment.public_ref} />,
          },
          {
            key: 'division',
            header: cop('division'),
            width: '12rem',
            cell: (assessment) => (
              <span data-sarana-datum="" className="font-mono text-xs">
                {assessment.gn_division_code}
              </span>
            ),
          },
          {
            key: 'category',
            header: disbursement('category'),
            width: '10rem',
            cell: (assessment) => <Badge tone="neutral">{assessment.category}</Badge>,
          },
          {
            key: 'estimate',
            header: t('costEstimate'),
            width: '13rem',
            numeric: true,
            // The officer's estimate, not an entitlement. The entitlement is what the cost
            // schedule makes of this, and the two are different numbers on purpose.
            cell: (assessment) => <LKRAmount cents={assessment.cost_estimate_lkr_cents} />,
          },
          {
            key: 'status',
            header: disbursement('approvalLevel'),
            width: '11rem',
            cell: (assessment) => (
              <Badge tone={assessment.status === 'ACCEPTED' ? 'verified' : 'pending'}>
                {assessment.status}
              </Badge>
            ),
          },
          {
            key: 'assessed',
            header: t('assessedAt'),
            cell: (assessment) => <RelativeTime value={assessment.assessed_at} />,
          },
        ]}
      />
    </div>
  );
}
