/**
 * The locale layout. This is the console's real root.
 *
 * `lang` is set from the URL segment, which is what selects the Noto face through the
 * `:lang()` rules in the design system's `tokens.css` and what tells a screen reader
 * which voice to use. A Tamil interface read by an English voice is not comprehensible,
 * so this attribute is load-bearing rather than a formality.
 *
 * `data-theme="dark"` because operations rooms run dark and a mid-range Android in the
 * field saves real battery on an OLED panel. The choice is the console's; the public
 * dashboard makes the opposite one for equally specific reasons.
 */

import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import type { Locale } from '@sarana/ts-shared/i18n';

import { AppShell } from '../../src/components/app-shell';
import { Providers } from '../../src/components/providers';
import { routing } from '../../src/i18n/routing';
import { readPrincipal } from '../../src/lib/session';

export const metadata: Metadata = {
  title: 'SARANA Operations Console',
  description:
    'Operator, GN officer and approver console for the SARANA disaster response platform.',
};

/** BCP-47 tags. `si` and `ta` alone would not tell a screen reader which region. */
const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: {
  readonly children: ReactNode;
  readonly params: Promise<{ readonly locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();

  setRequestLocale(locale);

  // Read once here rather than in each page. It is a cookie, so this is free, and it
  // means the navigation renders with the same claims the header does.
  const principal = await readPrincipal();

  return (
    <html lang={LANG_TAGS[locale]} data-theme="dark">
      <body>
        <NextIntlClientProvider>
          <Providers>
            <AppShell locale={locale} principal={principal}>
              {children}
            </AppShell>
          </Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
