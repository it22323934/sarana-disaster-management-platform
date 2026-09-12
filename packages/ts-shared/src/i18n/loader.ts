/**
 * Locale catalogue loading and message formatting.
 *
 * Catalogues are plain JSON, one file per locale, flattened to dotted keys at load time
 * so a lookup is a single object read rather than a walk.
 */

import { checkCompleteness, flatten } from './completeness.js';
import { DEFAULT_LOCALE, LOCALES, type Catalogue, type Locale } from './types.js';

export class MissingTranslationError extends Error {
  constructor(
    readonly locale: Locale,
    readonly key: string,
  ) {
    super(`no '${locale}' translation for '${key}'`);
    this.name = 'MissingTranslationError';
  }
}

export interface Translator {
  readonly locale: Locale;
  /** Look up a key, substituting `{name}` placeholders from `values`. */
  t(key: string, values?: Readonly<Record<string, string | number>>): string;
  /** Whether a key exists. Use to branch, never to silently drop a string. */
  has(key: string): boolean;
}

/**
 * Build a translator over three complete catalogues.
 *
 * Throws if the catalogues are not complete, so an incomplete build fails at startup
 * rather than rendering an English string to a Tamil-speaking citizen at run time.
 */
export function createTranslator(
  catalogues: Readonly<Record<Locale, unknown>>,
  locale: Locale = DEFAULT_LOCALE,
): Translator {
  const result = checkCompleteness(catalogues);
  if (!result.complete) {
    const summary = result.problems
      .slice(0, 5)
      .map((problem) => `${problem.locale}:${problem.key} (${problem.kind})`)
      .join(', ');
    throw new Error(
      `locale catalogues are incomplete (${result.problems.length} problems): ${summary}`,
    );
  }

  const flat = Object.fromEntries(
    LOCALES.map((candidate) => [candidate, flatten(catalogues[candidate])]),
  ) as Record<Locale, Catalogue>;

  const active = flat[locale];

  return {
    locale,
    has: (key) => key in active,
    t(key, values) {
      const template = active[key];
      if (template === undefined) {
        throw new MissingTranslationError(locale, key);
      }
      if (!values) return template;
      return template.replace(/\{(\w+)\}/g, (match, name: string) =>
        name in values ? String(values[name]) : match,
      );
    },
  };
}
