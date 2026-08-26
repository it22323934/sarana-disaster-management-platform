/**
 * The i18n completeness checker used by CI and by the pre-commit hook.
 *
 * Every locale catalogue must define exactly the same key set, and no value may be
 * blank. A missing Tamil string is not a cosmetic defect: during Cyclone Ditwah the
 * 28 Nov 2025 DMC press conference went out in Sinhala and English only, and
 * Tamil-speaking communities were left without the warning.
 */

import { LOCALES, type Catalogue, type Locale } from './types.js';

export interface CompletenessProblem {
  readonly locale: Locale;
  readonly key: string;
  readonly kind: 'missing' | 'blank';
}

export interface CompletenessResult {
  readonly complete: boolean;
  readonly problems: readonly CompletenessProblem[];
  readonly keyCount: number;
}

/** Flatten a nested catalogue into dotted key paths. */
export function flatten(value: unknown, prefix = ''): Catalogue {
  if (typeof value !== 'object' || value === null) {
    return prefix ? { [prefix]: String(value) } : {};
  }

  const out: Catalogue = {};
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof child === 'object' && child !== null) {
      Object.assign(out, flatten(child, path));
    } else {
      out[path] = String(child);
    }
  }
  return out;
}

/** Compare the three catalogues and report every missing or blank key. */
export function checkCompleteness(
  catalogues: Readonly<Record<Locale, unknown>>,
): CompletenessResult {
  const flattened = Object.fromEntries(
    LOCALES.map((locale) => [locale, flatten(catalogues[locale])]),
  ) as Record<Locale, Catalogue>;

  const allKeys = new Set<string>();
  for (const locale of LOCALES) {
    for (const key of Object.keys(flattened[locale])) allKeys.add(key);
  }

  const problems: CompletenessProblem[] = [];
  for (const key of [...allKeys].sort()) {
    for (const locale of LOCALES) {
      const value = flattened[locale][key];
      if (value === undefined) {
        problems.push({ locale, key, kind: 'missing' });
      } else if (value.trim().length === 0) {
        problems.push({ locale, key, kind: 'blank' });
      }
    }
  }

  return { complete: problems.length === 0, problems, keyCount: allKeys.size };
}

/** Render problems as lines a developer can act on. */
export function formatProblems(problems: readonly CompletenessProblem[]): string[] {
  return problems.map(
    (problem) => `  ${problem.locale}.json: key '${problem.key}' is ${problem.kind}`,
  );
}
