/**
 * `/ops/forecast` - impact forecasts by division, their drivers, and the triggers.
 *
 * This rendered `NotBuilt` until `GET /impact-forecasts` existed on agent-svc. The tables
 * behind it - `hazard.impact_forecast` and `hazard.anticipatory_trigger` - have been there
 * since file 04; nothing exposed them, so the forecast agent was writing to a surface no
 * human could read.
 */

import { setRequestLocale } from 'next-intl/server';

import { ForecastBoard } from '../../../../../src/components/forecast';

export default async function OpsForecastPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ForecastBoard />;
}
