/**
 * The money gate. One entitlement, one release.
 *
 * The principal is read server-side and passed down, because the segregation-of-duty line
 * compares the signed-in user against the entitlement's approval records and the client
 * should not have to fetch "who am I" before it can render that.
 */

import { setRequestLocale } from 'next-intl/server';

import { DisbursementGate } from '../../../../src/components/disbursement-gate';
import { readPrincipal } from '../../../../src/lib/session';

export default async function DisbursementGatePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly entitlementId: string }>;
}) {
  const { locale, entitlementId } = await params;
  setRequestLocale(locale);
  const principal = await readPrincipal();
  return <DisbursementGate entitlementId={entitlementId} principal={principal} />;
}
