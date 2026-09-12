/**
 * The site chrome: header, navigation, language switcher, footer.
 *
 * **Every one of these is a server component, and the language switcher is three plain
 * links.** The design system ships a `LanguageSwitcher` that is a client component with a
 * callback prop, which is right for the console — it swaps language without losing the
 * dispatch plan the operator is halfway through reading. Here it would be the only reason
 * this app shipped React to the browser at all, on a site whose core requirement is that
 * the numbers work with JavaScript switched off.
 *
 * Three `<a>` elements to the same path under a different locale prefix do the same job,
 * work with no JavaScript, are keyboard operable for free, and can be middle-clicked into
 * a new tab — which is what a journalist comparing the Tamil and English figures actually
 * does.
 */

import { MockDataBadge } from '@sarana/ui/server';
import { LOCALE_NAMES, LOCALES, type Locale } from '@sarana/ts-shared/i18n';
import { getTranslations } from 'next-intl/server';
import type { ReactNode } from 'react';

import { ROUTES, type Route } from '../i18n/routing';

export interface ChromeProps {
  readonly locale: Locale;
  /** The path below the locale prefix, e.g. `/districts`. Used to mark the current link. */
  readonly pathname: string;
}

function href(locale: Locale, route: string): string {
  return route === '/' ? `/${locale}` : `/${locale}${route}`;
}

const NAV_KEYS: Record<Route, string> = {
  '/': 'home',
  '/allocations': 'allocations',
  '/districts': 'districts',
  '/schedule': 'schedule',
  '/ledger': 'ledger',
  '/anchors': 'anchors',
  '/grievances': 'grievances',
  '/alerts': 'alerts',
  '/verify': 'verify',
  '/methodology': 'methodology',
};

export async function SiteHeader({ locale, pathname }: ChromeProps) {
  const t = await getTranslations({ locale, namespace: 'app' });
  const nav = await getTranslations({ locale, namespace: 'nav' });
  const common = await getTranslations({ locale, namespace: 'common' });

  return (
    <header className="border-b border-[var(--divider)] bg-[var(--surface-raised)]">
      <a
        href="#main"
        // Visible only when focused. The first thing a keyboard user meets on a site with
        // a ten-item navigation, and the difference between reaching the numbers in one
        // key press and in eleven.
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-[var(--radius-default)] focus:bg-[var(--surface-card)] focus:px-3 focus:py-2 focus:outline focus:outline-2 focus:outline-[var(--focus-ring)]"
      >
        {t('skipToContent')}
      </a>

      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <a
            href={href(locale, '/')}
            className="text-lg font-semibold text-[var(--text-primary)] no-underline"
          >
            {t('name')}
          </a>
          {/* Not dismissible, not shrinkable, and on every page. Every figure on this site
              comes from a mock government system, and the page a reader screenshots must
              say so inside the screenshot. */}
          <MockDataBadge locale={locale} />
        </div>

        <nav aria-label={common('language')} data-print-hide>
          <ul className="flex list-none items-center gap-1 p-0 text-xs">
            {LOCALES.map((candidate) => {
              const current = candidate === locale;
              return (
                <li key={candidate}>
                  <a
                    href={href(candidate, pathname)}
                    lang={candidate}
                    // The current language is marked for a screen reader and not removed
                    // as a link: a reader who lands on the wrong one needs the set to stay
                    // whole, and `aria-current` says which is active without hiding it.
                    aria-current={current ? 'true' : undefined}
                    className={
                      current
                        ? 'rounded-[var(--radius-cell)] bg-[var(--signal-100)] px-2 py-1 font-medium text-[var(--signal-700)] no-underline'
                        : 'rounded-[var(--radius-cell)] px-2 py-1 text-[var(--text-accent)] underline'
                    }
                  >
                    {LOCALE_NAMES[candidate]}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>

      <nav aria-label={nav('label')} data-site-nav className="border-t border-[var(--divider)]">
        <ul className="mx-auto flex max-w-6xl list-none flex-wrap gap-x-4 gap-y-1 px-4 py-2 text-sm">
          {ROUTES.map((route) => {
            const current = route === pathname;
            return (
              <li key={route}>
                <a
                  href={href(locale, route)}
                  aria-current={current ? 'page' : undefined}
                  className={
                    current
                      ? 'font-medium text-[var(--text-primary)] underline decoration-2 underline-offset-4'
                      : 'text-[var(--text-accent)] underline underline-offset-4'
                  }
                >
                  {nav(NAV_KEYS[route])}
                </a>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}

export async function SiteFooter({ locale }: { readonly locale: Locale }) {
  const t = await getTranslations({ locale, namespace: 'app' });
  const nav = await getTranslations({ locale, namespace: 'nav' });
  const methodology = await getTranslations({ locale, namespace: 'methodology' });

  return (
    <footer className="mt-12 border-t border-[var(--divider)] bg-[var(--surface-raised)]">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-sm">
        <p className="m-0 max-w-prose text-[var(--text-muted)]">{t('tagline')}</p>
        {/* The simulated-data statement is repeated in the footer in full sentences, not
            only as a badge. A badge is a glance; this is the sentence a reader quotes. */}
        <p className="m-0 max-w-prose font-medium text-[var(--text-primary)]">
          {methodology('simulatedTitle')}
        </p>
        <ul className="flex list-none flex-wrap gap-4 p-0" data-print-hide>
          <li>
            <a href={href(locale, '/methodology')} className="text-[var(--text-accent)] underline">
              {nav('methodology')}
            </a>
          </li>
          <li>
            <a href={href(locale, '/verify')} className="text-[var(--text-accent)] underline">
              {nav('verify')}
            </a>
          </li>
          <li>
            <a href={href(locale, '/grievances')} className="text-[var(--text-accent)] underline">
              {nav('grievances')}
            </a>
          </li>
        </ul>
      </div>
    </footer>
  );
}

/**
 * The wrapper every page body sits in.
 *
 * `id="main"` is what the skip link targets, and `tabIndex={-1}` is what makes the skip
 * actually move focus rather than only the scroll position — without it a screen reader
 * user lands visually on the content and keeps reading the navigation.
 */
export function PageShell({
  title,
  lead,
  children,
  actions,
}: {
  readonly title: ReactNode;
  readonly lead?: ReactNode;
  readonly children: ReactNode;
  readonly actions?: ReactNode;
}) {
  return (
    <main id="main" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-prose">
          <h1 className="m-0 text-2xl font-semibold text-[var(--text-primary)]">{title}</h1>
          {lead ? <p className="mt-2 text-[var(--text-muted)]">{lead}</p> : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap gap-2" data-print-hide>
            {actions}
          </div>
        ) : null}
      </div>
      {children}
    </main>
  );
}
