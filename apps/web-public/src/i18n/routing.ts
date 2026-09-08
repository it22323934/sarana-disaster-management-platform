/**
 * Locale routing for the public dashboard.
 *
 * The same shape as the console's, for a different and stronger reason. Every page here
 * exists to be linked to: a journalist pastes `/si/districts/LK-21` into a story, an
 * auditor bookmarks `/ta/verify`, a ministry circulates `/en/allocations`. A URL whose
 * language depends on the reader's cookie is a URL that shows two people different pages
 * and gives them no way to say which one they mean.
 *
 * `localePrefix: 'always'`, so there is exactly one URL per page per language and no
 * unprefixed twin that resolves differently for different readers.
 *
 * The cookie is deliberately long-lived here. The console's is a working month because
 * shifts share workstations; this is a public site read from a personal phone, and a
 * Tamil-speaking reader should not have to reselect their language every month.
 */

import { defineRouting } from 'next-intl/routing';
import { createNavigation } from 'next-intl/navigation';

import { DEFAULT_LOCALE, LOCALES } from '@sarana/ts-shared/i18n';

export const routing = defineRouting({
  locales: [...LOCALES],
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: 'always',
  localeCookie: { maxAge: 60 * 60 * 24 * 365 },
});

export const { Link, redirect, usePathname, useRouter, getPathname } = createNavigation(routing);

/**
 * The route inventory lives in `routes.ts` and is re-exported here.
 *
 * That module imports nothing, so a test can read the list without a Next runtime — this
 * one calls `createNavigation`, which reaches `next/navigation` and resolves only inside
 * one. The re-export keeps `routing` the single import a page needs.
 */
export { ROUTES, SAMPLE_DISTRICT_CODE, type Route } from './routes';
