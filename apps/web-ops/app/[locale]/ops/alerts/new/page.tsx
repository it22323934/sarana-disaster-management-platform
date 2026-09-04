/**
 * `/ops/alerts/new` - alert composition. Not built.
 */

import { setRequestLocale } from 'next-intl/server';

import { NotBuilt } from '../../../../../src/components/queues';

export default async function OpsAlertsNewPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <NotBuilt />;
}
