/**
 * Locale types shared by every SARANA surface.
 *
 * Non-negotiable #2 in the master context: no citizen-facing record may exist in only
 * one language. `LocalisedText` has no optional member and no single-string fallback -
 * a value that cannot satisfy all three locales does not get a type here.
 */

export const LOCALES = ['si', 'ta', 'en'] as const;

export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = 'en';

/** Display names, each written in its own language. Never translated. */
export const LOCALE_NAMES: Record<Locale, string> = {
  si: 'සිංහල',
  ta: 'தமிழ்',
  en: 'English',
};

/** A citizen-facing string. All three locales are required. */
export interface LocalisedText {
  readonly si: string;
  readonly ta: string;
  readonly en: string;
}

/** A flat catalogue of UI strings for one locale. */
export type Catalogue = Record<string, string>;

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && (LOCALES as readonly string[]).includes(value);
}

/**
 * Narrow an arbitrary value to LocalisedText.
 *
 * Used at the API boundary. A payload that fails this is a bug on the server side, not
 * something a UI should paper over with a fallback.
 */
export function isLocalisedText(value: unknown): value is LocalisedText {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return LOCALES.every(
    (locale) => typeof candidate[locale] === 'string' && candidate[locale].trim().length > 0,
  );
}

/**
 * Read a LocalisedText in the requested locale.
 *
 * The fallback covers an unrecognised locale setting, not a missing translation - by
 * construction there are none.
 */
export function localised(text: LocalisedText, locale: Locale): string {
  return text[locale] ?? text[DEFAULT_LOCALE];
}

/** Pick the best supported locale from an Accept-Language header, honouring q-values. */
export function negotiateLocale(header: string | null | undefined): Locale {
  if (!header) return DEFAULT_LOCALE;

  const ranked = header
    .split(',')
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(';');
      const qualityParam = params.find((param) => param.trim().startsWith('q='));
      const quality = qualityParam ? Number.parseFloat(qualityParam.trim().slice(2)) : 1;
      const primary = (tag ?? '').trim().toLowerCase().split('-')[0] ?? '';
      // Index breaks ties in header order, which is the documented behaviour.
      return { primary, score: (Number.isNaN(quality) ? 0 : quality) - index * 1e-6 };
    })
    .filter((entry): entry is { primary: Locale; score: number } => isLocale(entry.primary))
    .sort((a, b) => b.score - a.score);

  return ranked[0]?.primary ?? DEFAULT_LOCALE;
}
