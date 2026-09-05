/**
 * `/admin` - the template review gate and the cost schedules.
 */

import { setRequestLocale } from 'next-intl/server';

import { Admin } from '../../../src/components/admin';

export default async function AdminPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <Admin />;
}
