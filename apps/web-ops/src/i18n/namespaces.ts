/**
 * Which message namespaces each part of the console sends to the browser.
 *
 * The catalogue is serialised into the RSC payload of every page that mounts a
 * `NextIntlClientProvider`. At 579 keys that is roughly 22 KB of characters — **half the
 * HTML of the sign-in page**, which uses two namespaces of the twenty-five.
 *
 * `request.ts` still loads the whole catalogue server-side and that stays: a server
 * component may format any message, and splitting the *locale* load is the one thing this
 * product must not get wrong. What is split here is only what crosses to the client, and
 * only along a boundary the route tree already draws.
 *
 * **Two sets, not per-page.** A per-page list would be a second place to update every time
 * a screen used a new namespace, and forgetting it renders the key path to a district
 * office. The route groups are the boundary: `(auth)` is two small screens with a fixed
 * vocabulary, and `(console)` gets everything because the shell alone spans most of it.
 *
 * `tests/…/test_console_scopes.py` has a sibling in `verify-messages.ts`, which resolves
 * every literal `t('key')` against the catalogue — so a namespace missing from `AUTH_NAMESPACES`
 * is caught by the i18n gate rather than by a user.
 */

import type { Locale } from '@sarana/ts-shared/i18n';

/**
 * What the sign-in and step-up screens can reach.
 *
 * `app` for the product name, `common` for the language switcher and the shared verbs,
 * `auth` for the screens themselves, `errors` for a failed sign-in. Nothing else is
 * reachable from `(auth)`: there is no navigation, no gate banner and no queue.
 */
export const AUTH_NAMESPACES = ['app', 'common', 'auth', 'errors'] as const;

export type Messages = Record<string, unknown>;

/**
 * Narrow a catalogue to the named namespaces.
 *
 * A namespace that is absent from the catalogue is skipped rather than emitted as
 * `undefined`: next-intl treats an explicit `undefined` differently from an absent key,
 * and the difference shows up as a confusing runtime error rather than a missing string.
 */
export function pickNamespaces(
  messages: Messages,
  namespaces: readonly string[],
): Messages {
  const picked: Messages = {};
  for (const namespace of namespaces) {
    if (namespace in messages) picked[namespace] = messages[namespace];
  }
  return picked;
}

/** Every namespace in a catalogue. The console group sends all of them. */
export function allNamespaces(messages: Messages): readonly string[] {
  return Object.keys(messages);
}

/** Kept so a test can assert the auth set is a real subset rather than a typo list. */
export type AuthNamespace = (typeof AUTH_NAMESPACES)[number];

export type { Locale };
