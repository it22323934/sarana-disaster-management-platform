/**
 * `/approvals/[id]` - one entitlement, read before it is signed.
 *
 * The queue says what is waiting and for which level; this is where the calculation is
 * actually read. It renders the same `CalculationTrace` as the money gate, deliberately:
 * the approver who signs and the releaser who pays must be looking at one derivation.
 */

import { setRequestLocale } from 'next-intl/server';

import { ApprovalDetail } from '../../../../../src/components/approval-detail';

export default async function ApprovalDetailPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string; readonly entitlementId: string }>;
}) {
  const { locale, entitlementId } = await params;
  setRequestLocale(locale);
  return <ApprovalDetail entitlementId={entitlementId} />;
}
