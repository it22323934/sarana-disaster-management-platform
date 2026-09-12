/**
 * `/disbursements` — releases awaiting approval.
 *
 * The list is of *entitlements* that are ready to release, not of disbursements: a
 * disbursement is what exists after the gate, so a queue of them would be a list of work
 * already done.
 */

import { setRequestLocale } from 'next-intl/server';

import { ReleaseQueue } from '../../../../src/components/release-queue';

export default async function DisbursementsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ReleaseQueue />;
}
