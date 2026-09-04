/**
 * `/ops/alerts` - drafted and dispatched alerts.
 */

import { setRequestLocale } from 'next-intl/server';

import { AlertList } from '../../../../src/components/alerts';

export default async function AlertListPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AlertList />;
}
