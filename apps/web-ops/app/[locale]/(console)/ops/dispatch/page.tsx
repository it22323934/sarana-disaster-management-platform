/**
 * `/ops/dispatch` — everything waiting for a dispatch decision.
 */

import { setRequestLocale } from 'next-intl/server';

import { DispatchQueue } from '../../../../../src/components/dispatch-queue';

export default async function DispatchQueuePage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <DispatchQueue />;
}
