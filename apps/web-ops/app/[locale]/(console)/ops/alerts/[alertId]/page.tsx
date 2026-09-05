/**
 * `/ops/alerts/[id]` - the draft, its mandatory dry run, and the send.
 *
 * Separate from the composer on purpose. The composer creates a draft and stops; this is
 * where a dry run happens and only then a send. One button that drafted and sent is how a
 * national fan-out happens by accident.
 */

import { setRequestLocale } from 'next-intl/server';

import { AlertDispatch } from '../../../../../../src/components/alert-dispatch';

export default async function AlertDispatchPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly alertId: string }>;
}) {
  const { locale, alertId } = await params;
  setRequestLocale(locale);
  return <AlertDispatch alertId={alertId} />;
}
