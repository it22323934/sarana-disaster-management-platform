/**
 * `/ops/incidents` - the incident list.
 */

import { setRequestLocale } from 'next-intl/server';

import { IncidentList } from '../../../../../src/components/incidents';

export default async function IncidentListPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <IncidentList />;
}
