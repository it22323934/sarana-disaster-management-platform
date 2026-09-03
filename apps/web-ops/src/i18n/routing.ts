/**
 * Locale routing.
 *
 * The locale is in the URL (`/si/ops/dispatch`), not only in a cookie. Three reasons that
 * matter for this product: a shared link to a dispatch plan opens in the language the
 * sender was reading it in, the a11y and visual checks can address every route in every
 * script, and a Tamil-speaking officer's bookmark stays Tamil after a session expires.
 *
 * `localePrefix: 'always'` rather than hiding the default: an unprefixed URL alongside
 * prefixed ones means two URLs for the same page, and the one people paste into a
 * situation report would be the one whose language depends on the reader's cookie.
 */

import { defineRouting } from 'next-intl/routing';
import { createNavigation } from 'next-intl/navigation';

import { DEFAULT_LOCALE, LOCALES } from '@sarana/ts-shared/i18n';

export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: 'always',
  localeCookie: {
    // The console is used across shifts on shared workstations, so the preference is
    // remembered for a working month rather than a year.
    maxAge: 60 * 60 * 24 * 30,
  },
});

export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);
