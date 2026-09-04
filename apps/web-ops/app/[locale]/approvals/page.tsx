/**
 * `/approvals` - entitlement approvals. Not built.
 */

import { setRequestLocale } from 'next-intl/server';

import { NotBuilt } from '../../../src/components/queues';

export default async function ApprovalsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <NotBuilt />;
}
