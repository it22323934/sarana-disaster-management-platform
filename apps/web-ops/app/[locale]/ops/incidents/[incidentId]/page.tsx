/**
 * `/ops/incidents/[id]` - one incident, with what its location confidence means.
 */

import { setRequestLocale } from 'next-intl/server';

import { IncidentDetail } from '../../../../../src/components/incidents';

export default async function IncidentDetailPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly incidentId: string }>;
}) {
  const { locale, incidentId } = await params;
  setRequestLocale(locale);
  return <IncidentDetail incidentId={incidentId} />;
}
