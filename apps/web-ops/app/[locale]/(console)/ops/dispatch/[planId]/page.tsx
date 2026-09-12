/**
 * The dispatch gate. One plan, one decision.
 *
 * A Server Component that renders a Client one: the plan id comes from the route and the
 * screen itself is live, so there is nothing to gain from fetching here — and something
 * to lose, because a server-fetched plan would be a snapshot from page load while the
 * banner above it polls every five seconds.
 */

import { setRequestLocale } from 'next-intl/server';

import { DispatchGate } from '../../../../../../src/components/dispatch-gate';

export default async function DispatchGatePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly planId: string }>;
}) {
  const { locale, planId } = await params;
  setRequestLocale(locale);
  return <DispatchGate planId={planId} />;
}
