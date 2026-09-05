/**
 * `/ops` — the common operating picture.
 */

import { setRequestLocale } from 'next-intl/server';

import { CommonOperatingPicture } from '../../../../src/components/common-operating-picture';

export default async function OpsPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <CommonOperatingPicture />;
}
