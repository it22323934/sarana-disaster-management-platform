'use client';

/**
 * The review queue, the grievance queue, and the placeholder for what is not built.
 *
 * `NotBuilt` is deliberate rather than lazy. The navigation lists every route in the
 * brief, and a link that 404s tells an operator the console is broken; a link that says
 * "this screen is not built yet, nothing is hidden behind it" tells them the truth. During
 * a demo the difference matters — a 404 invites the conclusion that something failed.
 */

import { Badge, ConfidenceMeter, DataTable, EmptyState, ReferenceCode, RelativeTime } from '@sarana/ui';
import type { ConfidenceBand } from '@sarana/ui';
import { useTranslations } from 'next-intl';

import { useGrievanceList, useReviewQueue } from '../lib/queries';
import type { Grievance, ReviewItem } from '../lib/schemas';
import { ErrorPanel } from './degraded';

/** Below this a transcription is held for a person rather than acted on. */
const REVIEW_THRESHOLD = 0.7;

function bandFor(confidence: number): ConfidenceBand {
  if (confidence >= 0.85) return 'high';
  if (confidence >= REVIEW_THRESHOLD) return 'medium';
  return 'low';
}

export function ReviewQueue() {
  const t = useTranslations('review');
  const reviews = useReviewQueue();

  if (reviews.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={reviews.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      <DataTable<ReviewItem>
        caption={t('title')}
        rows={reviews.data ?? []}
        rowKey={(item) => item.id}
        height="calc(100vh - 16rem)"
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'ref',
            header: t('title'),
            width: '12rem',
            cell: (item) => <ReferenceCode code={item.id.slice(0, 8)} />,
          },
          {
            key: 'language',
            header: t('language'),
            width: '8rem',
            cell: (item) => <Badge tone="neutral">{item.language ?? '—'}</Badge>,
          },
          {
            key: 'confidence',
            header: t('confidence'),
            width: '18rem',
            cell: (item) =>
              item.confidence === null ? (
                '—'
              ) : (
                // The consequence is the point: this item is here *because* the number is
                // low, and saying so is what stops the number being scrolled past.
                <ConfidenceMeter
                  value={item.confidence}
                  band={bandFor(item.confidence)}
                  bandLabel={t('confidence')}
                  consequence={t('emptyHint')}
                />
              ),
          },
          {
            key: 'transcript',
            header: t('transcript'),
            cell: (item) => (
              // The original-language text, with `lang` so it renders in the right face
              // and a screen reader uses the right voice.
              <span lang={item.language ?? undefined} className="text-xs">
                {item.transcript ?? '—'}
              </span>
            ),
          },
        ]}
      />
    </div>
  );
}

export function GrievanceQueue() {
  const t = useTranslations('grievances');
  const grievances = useGrievanceList();

  if (grievances.isError) {
    return (
      <div className="p-6">
        <ErrorPanel error={grievances.error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-6">
      <h1 className="text-xl font-semibold">{t('title')}</h1>

      <DataTable<Grievance>
        caption={t('title')}
        rows={grievances.data ?? []}
        rowKey={(grievance) => grievance.id}
        height="calc(100vh - 16rem)"
        empty={<EmptyState title={t('empty')} description={t('emptyHint')} />}
        columns={[
          {
            key: 'ref',
            header: t('title'),
            width: '15rem',
            cell: (grievance) => (
              <ReferenceCode code={grievance.public_ref ?? grievance.id.slice(0, 8)} />
            ),
          },
          {
            key: 'category',
            header: t('category'),
            width: '14rem',
            cell: (grievance) => <Badge tone="neutral">{grievance.category ?? '—'}</Badge>,
          },
          {
            key: 'status',
            header: t('status'),
            width: '12rem',
            cell: (grievance) => (
              <Badge tone={grievance.status === 'RESOLVED' ? 'verified' : 'pending'}>
                {grievance.status}
              </Badge>
            ),
          },
          {
            key: 'raised',
            header: t('raised'),
            cell: (grievance) =>
              grievance.raised_at ? <RelativeTime value={grievance.raised_at} /> : '—',
          },
        ]}
      />
    </div>
  );
}

/**
 * A route the brief names and this build does not have.
 *
 * It says so plainly, in the operator's language, and says that nothing is hidden behind
 * it. That is a better answer than a 404 and a much better answer than an empty screen
 * that looks like a failed request.
 */
export function NotBuilt() {
  const t = useTranslations('notBuilt');
  return (
    <div className="p-6">
      <EmptyState title={t('title')} description={t('body')} />
    </div>
  );
}
