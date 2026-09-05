/**
 * Sign-in and step-up: outside the console shell, and with a narrowed catalogue.
 *
 * No navigation, no gate banner and no disaster spine. A signed-out browser has nothing to
 * navigate to, and the banner would poll `dispatch-plans` and `entitlements` every five
 * seconds against a session that does not exist - a steady stream of 401s in the server
 * logs from the one page guaranteed to be open before anybody has signed in.
 *
 * The messages are narrowed to what these two screens can reach. The full catalogue is 579
 * keys and was half the HTML of this page; these screens use four namespaces.
 */

import { NextIntlClientProvider } from 'next-intl';
import { getMessages, setRequestLocale } from 'next-intl/server';
import type { ReactNode } from 'react';

import { AUTH_NAMESPACES, pickNamespaces } from '../../../src/i18n/namespaces';

export default async function AuthLayout({
  children,
  params,
}: {
  readonly children: ReactNode;
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);

  const messages = await getMessages();

  return (
    <NextIntlClientProvider messages={pickNamespaces(messages, AUTH_NAMESPACES)}>
      {children}
    </NextIntlClientProvider>
  );
}
