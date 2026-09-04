/**
 * `/audit/chain` - recompute the hash chain and read the published daily anchors.
 */

import { setRequestLocale } from 'next-intl/server';

import { ChainVerification } from '../../../../src/components/chain';

export default async function ChainPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <ChainVerification />;
}
