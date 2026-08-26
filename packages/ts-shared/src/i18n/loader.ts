// Locale catalogue loader — si / ta / en, plus the completeness check CI and
// pre-commit both call to fail the build on a missing key (docs/build-prompts/03).
//
// NOTE: locales/si.json and locales/ta.json are a provisional starting draft, not
// reviewed copy. Per docs/build-prompts/00-master-context.md and 09-alerting-service.md,
// no citizen-facing text ships without a named Sinhala reviewer and a named Tamil
// reviewer signing off — that applies to every string here, not only alert templates.

import en from "./locales/en.json";
import si from "./locales/si.json";
import ta from "./locales/ta.json";

export const SUPPORTED_LOCALES = ["si", "ta", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

const CATALOGUE: Record<Locale, unknown> = { si, ta, en };

export function getMessages(locale: Locale): unknown {
  const messages = CATALOGUE[locale];
  if (!messages) {
    throw new Error(`Unknown locale: ${locale}`);
  }
  return messages;
}

/** Recursively collect every leaf key path in a message tree, e.g. "common.loading". */
function collectKeyPaths(obj: unknown, prefix = ""): string[] {
  if (obj === null || typeof obj !== "object") {
    return [prefix];
  }
  return Object.entries(obj as Record<string, unknown>).flatMap(([key, value]) =>
    collectKeyPaths(value, prefix ? `${prefix}.${key}` : key),
  );
}

export interface CompletenessResult {
  complete: boolean;
  /** locale -> key paths present in at least one other locale but missing here */
  missingByLocale: Partial<Record<Locale, string[]>>;
}

/**
 * Fails closed: every key path present in ANY locale must be present in ALL locales.
 * This is what backs `make verify-i18n` and the pre-commit i18n hook.
 */
export function completeness(
  locales: Partial<Record<Locale, unknown>> = CATALOGUE,
): CompletenessResult {
  const keysByLocale: Partial<Record<Locale, Set<string>>> = {};
  const allKeys = new Set<string>();

  for (const [locale, messages] of Object.entries(locales) as [Locale, unknown][]) {
    const keys = new Set(collectKeyPaths(messages));
    keysByLocale[locale] = keys;
    for (const k of keys) allKeys.add(k);
  }

  const missingByLocale: Partial<Record<Locale, string[]>> = {};
  for (const [locale, keys] of Object.entries(keysByLocale) as [Locale, Set<string>][]) {
    const missing = [...allKeys].filter((k) => !keys.has(k));
    if (missing.length > 0) {
      missingByLocale[locale] = missing.sort();
    }
  }

  return { complete: Object.keys(missingByLocale).length === 0, missingByLocale };
}
