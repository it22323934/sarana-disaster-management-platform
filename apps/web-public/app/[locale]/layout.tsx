/**
 * The locale layout. This is the site's real root.
 *
 * `lang` is set from the URL segment, which selects the Noto face through the `:lang()`
 * rules in the design system's `tokens.css` and tells a screen reader which voice to use.
 * A Tamil page read by an English voice is not comprehensible, so the attribute is
 * load-bearing rather than a formality.
 *
 * `data-theme="light"` is the opposite of the console's choice and for equally specific
 * reasons: this page is read in daylight on a phone, screenshotted into articles, and
 * printed. A dark screenshot pasted into a newspaper layout inverts to a grey block, and a
 * dark page printed costs a cartridge.
 *
 * **There is no `NextIntlClientProvider`.** The console wraps its route groups in one
 * because its panels are client components that call `useTranslations` at run time. Every
 * page here is a server component that formats its messages during render, so the
 * catalogue never needs to reach the browser — which is most of how the initial route
 * stays inside the brief's 120 KB budget, and all of why the numbers survive with
 * JavaScript switched off.
 */

import { hasLocale } from 'next-intl';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import type { Locale } from '@sarana/ts-shared/i18n';

import { routing } from '../../src/i18n/routing';

/** BCP-47 tags. `si` and `ta` alone would not tell a screen reader which region. */
const LANG_TAGS: Record<Locale, string> = { si: 'si-LK', ta: 'ta-LK', en: 'en-LK' };

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params,
}: {
  readonly params: Promise<{ readonly locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return {};

  const t = await getTranslations({ locale, namespace: 'app' });

  return {
    title: { default: t('name'), template: `%s · ${t('name')}` },
    description: t('tagline'),
    // No indexing directive and no analytics. The brief allows aggregate page counts and
    // nothing more; there is no script here to collect anything else.
    openGraph: { title: t('name'), description: t('tagline'), locale: LANG_TAGS[locale] },
  };
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

  return (
    <html lang={LANG_TAGS[locale]} data-theme="light">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
