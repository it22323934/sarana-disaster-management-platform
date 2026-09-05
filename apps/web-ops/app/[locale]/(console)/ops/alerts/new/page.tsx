/**
 * `/ops/alerts/new` - alert composition.
 *
 * Template selection, typed parameters, a live preview in all three languages with the
 * SMS segment cost under each, free text that visibly forces sign-off, and the mandatory
 * dry run. The one thing it cannot do is create the draft: `POST /alerts` needs a
 * `hazard_event_id` and no service lists hazard events - see the handoff.
 */

import { setRequestLocale } from 'next-intl/server';

import { AlertComposer } from '../../../../../../src/components/alert-composer';

export default async function AlertComposerPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AlertComposer />;
}
