/**
 * `/audit/anomalies` - flags, their innocent explanations, and the disposition workflow.
 */

import { setRequestLocale } from 'next-intl/server';

import { AnomalyReview } from '../../../../../src/components/audit';

export default async function AnomalyReviewPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AnomalyReview />;
}
