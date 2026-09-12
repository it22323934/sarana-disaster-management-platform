/**
 * Per-request i18n configuration.
 *
 * **The catalogue is loaded whole, and that is separate from what reaches the browser.**
 * A server component may format any message, so the server needs all of it; splitting the
 * *locale* load is the one thing this product must not get wrong, because the failure mode
 * is a route rendering in the wrong language or in none.
 *
 * What crosses to the client is narrowed, by route group, in `src/i18n/namespaces.ts`. That
 * split was worth making once the catalogue passed 579 keys: serialised into every page it
 * was roughly 22 KB of characters and **half the HTML of the sign-in page**, which can
 * reach two namespaces of the twenty-five.
 */

import { getRequestConfig } from 'next-intl/server';
import { hasLocale } from 'next-intl';

import { routing } from './routing';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;

  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    // Everything the platform stores is UTC and everything it shows is Colombo. Setting
    // it here means a component that formats a date without saying so still gets it
    // right, rather than rendering the server's timezone in a Docker container set to UTC.
    timeZone: 'Asia/Colombo',
    onError(error) {
      // A missing message is a build-time failure (verify-i18n) and a loud one at run
      // time. Swallowing it is how a key ships as a raw dotted path to a district office.
      console.error('[i18n]', error);
    },
  };
});
