// Admin-code display names for the frontend — turns "LK-21-05-014" into a trilingual
// label a human reads, given the reference data the API already returned. This module
// never guesses a name from a code; it only formats one that came with a label attached.

import type { Locale } from "../i18n/loader";

export interface AdminCodeLabel {
  code: string;
  name: Record<Locale, string>;
}

/** "Kandy (LK-21)" style display, in the given locale, with the code always visible —
 * per docs/build-prompts/00-master-context.md, never a free-text name used as the key,
 * so the code stays visible alongside the name everywhere it's shown. */
export function formatAdminLabel(label: AdminCodeLabel, locale: Locale): string {
  return `${label.name[locale]} (${label.code})`;
}
