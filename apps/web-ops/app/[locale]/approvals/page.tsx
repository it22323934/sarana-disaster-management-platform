/**
 * `/approvals` - entitlements waiting for a DS or District signature.
 */

import { setRequestLocale } from 'next-intl/server';

import { ApprovalQueue } from '../../../src/components/approvals';

export default async function ApprovalsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ApprovalQueue />;
}
