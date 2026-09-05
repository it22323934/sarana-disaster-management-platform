/**
 * Everything behind the navigation.
 *
 * A route group, so `(console)` never appears in a URL: `/en/ops` is still `/en/ops`. What
 * it buys is the thing a nested passthrough layout could not — the sign-in and step-up
 * screens in `(auth)` genuinely sit outside this shell rather than inside a layout that
 * happened to render only its children.
 *
 * The principal is read once here rather than in each page. It is a cookie, so this is
 * free, and it means the navigation renders from the same claims the header does.
 */

import { NextIntlClientProvider } from 'next-intl';
import { getMessages, setRequestLocale } from 'next-intl/server';
import type { ReactNode } from 'react';

import type { Locale } from '@sarana/ts-shared/i18n';

import { AppShell } from '../../../src/components/app-shell';
import { readPrincipal } from '../../../src/lib/session';

export default async function ConsoleLayout({
  children,
  params,
}: {
  readonly children: ReactNode;
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const principal = await readPrincipal();
  // The whole catalogue, unlike `(auth)`. The shell alone spans most of it - navigation,
  // the gate banner, the spine, the degraded states - and narrowing per page would be a
  // second list to forget, which renders a key path to a district office.
  const messages = await getMessages();

  return (
    <NextIntlClientProvider messages={messages}>
      <AppShell locale={locale as Locale} principal={principal}>
        {children}
      </AppShell>
    </NextIntlClientProvider>
  );
}
