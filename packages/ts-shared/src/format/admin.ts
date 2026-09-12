/**
 * Administrative code parsing and display.
 *
 * Codes are the key; the place name is only ever a label. `LK-11-03-045` identifies a
 * GN division unambiguously, `Kadawatha` does not - several divisions share a name and
 * transliteration between Sinhala, Tamil and English is not one-to-one.
 */

import type { LocalisedText } from '../i18n/types.js';

export type AdminLevel = 'national' | 'province' | 'district' | 'ds_division' | 'gn_division';

const PATTERNS: ReadonlyArray<readonly [RegExp, AdminLevel]> = [
  [/^LK$/, 'national'],
  [/^LK-P\d{2}$/, 'province'],
  [/^LK-\d{2}$/, 'district'],
  [/^LK-\d{2}-\d{2}$/, 'ds_division'],
  [/^LK-\d{2}-\d{2}-\d{3}$/, 'gn_division'],
];

export class InvalidAdminCodeError extends Error {
  constructor(readonly code: string) {
    super(`not a recognised Sri Lanka administrative code: ${code}`);
    this.name = 'InvalidAdminCodeError';
  }
}

/** Infer the hierarchy level from a code's shape. */
export function adminLevel(code: string): AdminLevel {
  for (const [pattern, level] of PATTERNS) {
    if (pattern.test(code)) return level;
  }
  throw new InvalidAdminCodeError(code);
}

export function isAdminCode(code: string): boolean {
  return PATTERNS.some(([pattern]) => pattern.test(code));
}

/** The district component of a district, DS or GN code. */
export function districtOf(code: string): string {
  const level = adminLevel(code);
  if (level !== 'district' && level !== 'ds_division' && level !== 'gn_division') {
    throw new InvalidAdminCodeError(code);
  }
  return code.split('-').slice(0, 2).join('-');
}

/** The DS division component of a DS or GN code. */
export function dsOf(code: string): string {
  const level = adminLevel(code);
  if (level !== 'ds_division' && level !== 'gn_division') {
    throw new InvalidAdminCodeError(code);
  }
  return code.split('-').slice(0, 3).join('-');
}

/**
 * Whether a scope code covers a target code.
 *
 * Segment-aware, so `LK-11-0` never accidentally covers `LK-11-03`. Province scopes are
 * not decidable from codes alone and must be expanded to districts first - the same rule
 * the Python side enforces.
 */
export function covers(scopeCode: string, targetCode: string): boolean {
  if (scopeCode === 'LK') return true;
  if (adminLevel(scopeCode) === 'province') {
    throw new Error(
      'province scope cannot be resolved from codes alone; expand it to district codes first',
    );
  }
  return scopeCode === targetCode || targetCode.startsWith(`${scopeCode}-`);
}

export interface AdminUnitLabel {
  readonly code: string;
  readonly name: LocalisedText;
}

/**
 * Render a breadcrumb from ancestor to target, e.g. `Kandy › Ganga Ihala Korale › Pallekele`.
 *
 * Takes an already-resolved chain rather than looking anything up: name resolution needs
 * the reference table and belongs in a data layer, not a formatter.
 */
export function formatAdminPath(
  chain: readonly AdminUnitLabel[],
  locale: keyof LocalisedText,
  separator = ' \u203a ',
): string {
  return chain.map((unit) => unit.name[locale]).join(separator);
}

/** Human-readable level name for a code, used in table headers and filter labels. */
export const ADMIN_LEVEL_LABELS: Record<AdminLevel, LocalisedText> = {
  national: { si: 'ජාතික', ta: 'தேசிய', en: 'National' },
  province: { si: 'පළාත', ta: 'மாகாணம்', en: 'Province' },
  district: { si: 'දිස්ත්‍රික්කය', ta: 'மாவட்டம்', en: 'District' },
  ds_division: { si: 'ප්‍රාදේශීය ලේකම් කොට්ඨාසය', ta: 'பிரதேச செயலகப் பிரிவு', en: 'DS Division' },
  gn_division: { si: 'ග්‍රාම නිලධාරී වසම', ta: 'கிராம சேவகர் பிரிவு', en: 'GN Division' },
};
