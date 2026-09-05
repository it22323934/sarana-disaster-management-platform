/**
 * `/grievances` - the grievance queue.
 */

import { setRequestLocale } from 'next-intl/server';

import { GrievanceQueue } from '../../../../src/components/queues';

export default async function GrievanceQueuePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <GrievanceQueue />;
}
