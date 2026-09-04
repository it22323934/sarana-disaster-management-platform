/**
 * `/audit` - the ledger browser.
 */

import { setRequestLocale } from 'next-intl/server';

import { AuditLedger } from '../../../src/components/audit';

export default async function AuditLedgerPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <AuditLedger />;
}
