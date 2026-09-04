/**
 * `/ops/forecast` - impact forecasts. Not built.
 */

import { setRequestLocale } from 'next-intl/server';

import { NotBuilt } from '../../../../src/components/queues';

export default async function OpsForecastPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <NotBuilt />;
}
