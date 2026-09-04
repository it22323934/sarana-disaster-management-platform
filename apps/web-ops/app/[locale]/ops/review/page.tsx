/**
 * `/ops/review` - low-confidence transcriptions.
 */

import { setRequestLocale } from 'next-intl/server';

import { ReviewQueue } from '../../../../src/components/queues';

export default async function ReviewQueuePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ReviewQueue />;
}
