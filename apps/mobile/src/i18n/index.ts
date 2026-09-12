/**
 * Language on the device.
 *
 * Chosen on first launch, **before login**, and changeable at any time. Before login,
 * because the sign-in screen is itself a citizen-facing string: an app that asks for a
 * phone number in a language the user does not read has already failed.
 *
 * All three scripts are bundled in the binary. Nothing is fetched at run time - the one
 * moment a citizen most needs to read a warning is the moment the network is worst.
 */

import { getLocales } from 'expo-localization';
import {
  DEFAULT_LOCALE,
  LOCALES,
  LOCALE_NAMES,
  createTranslator,
  isLocale,
  type Locale,
  type Translator,
} from '@sarana/ts-shared/i18n';

import en from './catalogue/en.json';
import si from './catalogue/si.json';
import ta from './catalogue/ta.json';

export { DEFAULT_LOCALE, LOCALES, LOCALE_NAMES, isLocale };
export type { Locale, Translator };

const CATALOGUES: Record<Locale, unknown> = { si, ta, en };

/**
 * Build the translator for a locale.
 *
 * `createTranslator` throws if the three catalogues are not complete, so an incomplete
 * build fails at start-up rather than rendering an English string to a Tamil-speaking
 * citizen during a cyclone. `scripts/verify-i18n.ts` catches it earlier, in CI.
 */
export function translator(locale: Locale): Translator {
  return createTranslator(CATALOGUES, locale);
}

export interface LocaleChoice {
  readonly locale: Locale;
  /**
   * Whether the picker is shown immediately on first launch.
   *
   * True when the device locale is not one SARANA speaks. Defaulting such a device to
   * English silently would leave a Tamil speaker with an English app and no obvious way
   * out, so the picker is put in front of them instead.
   */
  readonly promptImmediately: boolean;
}

/**
 * The starting locale, from the device.
 *
 * `stored` is what the user chose last; it always wins. Nothing here overrides an
 * explicit choice, including a later OS language change - someone who set the app to
 * Tamil on a phone that is in English meant it.
 */
export function initialLocale({
  stored,
  deviceLocales = getLocales().map((entry) => entry.languageCode ?? ''),
}: {
  stored?: string | null;
  deviceLocales?: readonly (string | null)[];
} = {}): LocaleChoice {
  if (isLocale(stored)) return { locale: stored, promptImmediately: false };

  for (const candidate of deviceLocales) {
    const primary = (candidate ?? '').toLowerCase().split('-')[0] ?? '';
    if (isLocale(primary)) return { locale: primary, promptImmediately: false };
  }

  return { locale: DEFAULT_LOCALE, promptImmediately: true };
}
