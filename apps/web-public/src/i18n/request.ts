/**
 * Per-request i18n configuration.
 *
 * The catalogue is loaded whole on the server, exactly as in the console: a server
 * component may format any message, and splitting the *locale* load is the one thing a
 * trilingual product must not get wrong.
 *
 * **Unlike the console, almost nothing crosses to the browser.** web-ops narrows what it
 * sends by route group because its panels are client components that need `useTranslations`
 * at run time. This app has three client components in total, and none of them formats a
 * message it was not handed as a prop. So there is no `NextIntlClientProvider` around the
 * site and no catalogue in the RSC payload - which is most of how the initial route stays
 * under the brief's 120 KB budget, and all of why the pages still read correctly with
 * JavaScript switched off.
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
    // Everything the platform stores is UTC and everything it shows is Colombo. Setting it
    // here means a component that formats a date without saying so still gets it right,
    // rather than rendering the server's timezone from a container set to UTC.
    timeZone: 'Asia/Colombo',
    onError(error) {
      // A missing message is a build-time failure (verify-i18n) and a loud one at run
      // time. Swallowing it is how a key ships as a raw dotted path onto a public page.
      console.error('[i18n]', error);
    },
  };
});
