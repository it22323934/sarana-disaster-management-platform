/**
 * `/audit/chain` - chain verification. Not built.
 */

import { setRequestLocale } from 'next-intl/server';

import { NotBuilt } from '../../../../src/components/queues';

export default async function AuditChainPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <NotBuilt />;
}
