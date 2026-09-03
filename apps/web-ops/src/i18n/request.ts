/**
 * Per-request i18n configuration.
 *
 * Messages are loaded whole rather than split per route. The catalogue is 158 keys and a
 * few kilobytes; splitting it would save nothing measurable and would introduce the one
 * failure mode this product cannot have — a route that renders with the wrong locale's
 * chunk, or with none.
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
