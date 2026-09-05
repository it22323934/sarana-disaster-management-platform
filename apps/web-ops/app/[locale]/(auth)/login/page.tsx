/**
 * `/login`.
 *
 * Rendered outside the console shell: there is no navigation to show and no pending-gate
 * banner to poll, and a signed-out browser polling the gate endpoint every five seconds
 * would be a stream of 401s in the server logs.
 */

import { setRequestLocale } from 'next-intl/server';

import { SignInForm } from '../../../../src/components/sign-in-form';

export default async function LoginPage({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <SignInForm locale={locale} />;
}
