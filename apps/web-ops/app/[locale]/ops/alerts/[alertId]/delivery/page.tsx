/**
 * `/ops/alerts/[id]/delivery` - delivery counts and the divisions that probably did not get it.
 */

import { setRequestLocale } from 'next-intl/server';

import { DeliveryPanel } from '../../../../../../src/components/alerts';

export default async function DeliveryPanelPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly alertId: string }>;
}) {
  const { locale, alertId } = await params;
  setRequestLocale(locale);
  return <DeliveryPanel alertId={alertId} />;
}
