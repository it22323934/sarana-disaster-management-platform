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
 *
 * **It renders no shell.** The navigation and the pending-gate banner live in
 * `(console)/layout.tsx`, and the sign-in and step-up screens sit in `(auth)` beside it —
 * which is what the brief's own `/(auth)/login` notation means.
 *
 * That split used to be attempted with a nested `login/layout.tsx` returning only its
 * children, on the belief that it *replaced* the parent. Nested layouts in the App Router
 * **compose**; they do not replace. So the sign-in page rendered the whole console shell,
 * and `PendingGates` inside it polled `dispatch-plans` and `entitlements` every five
 * seconds at a signed-out browser — a steady stream of 401s, which is precisely the thing
 * that file's docstring said it was avoiding. A route group is the mechanism that actually
 * does it.
 */

import { hasLocale } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import type { Locale } from '@sarana/ts-shared/i18n';

import { Providers } from '../../src/components/providers';
import { routing } from '../../src/i18n/routing';

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

  return (
    <html lang={LANG_TAGS[locale]} data-theme="dark">
      <body>
        {/* No message provider here. Each route group supplies its own, narrowed to what
            that subtree can actually reach - see `src/i18n/namespaces.ts`. Providing the
            whole catalogue at this level put all 579 keys into the sign-in page, where
            they were half the HTML and two of them were reachable. */}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
