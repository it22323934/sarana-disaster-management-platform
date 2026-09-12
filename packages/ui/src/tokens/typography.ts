/**
 * Type: the part of this system that carries the trilingual commitment.
 *
 * Sinhala, Tamil and Latin have different x-heights, different ascender and descender
 * behaviour and different glyph density. A scale tuned for Latin renders Sinhala and
 * Tamil as an afterthought - clipped ascenders, cramped leading, a paragraph that looks
 * like a machine translation of the "real" one. That is precisely the failure this
 * platform exists to fix, so the scale is tuned so all three scripts sit at equal optical
 * weight and the same sentence occupies comparable space in each.
 *
 * The per-script numbers below were tuned against real strings from
 * `packages/ts-shared/src/i18n/locales/*.json` and the seeded alert templates, not
 * against lorem. Sinhala in particular has tall ascenders (ේ, ෞ) and deep descenders (ුු)
 * that collide across lines at Latin leading.
 */

import type { Locale } from '@sarana/ts-shared/i18n';

/**
 * Font stacks, one per script.
 *
 * Script selection is automatic, via `:lang(si)` and `:lang(ta)` and a stack that puts
 * the right Noto face first. Nothing switches fonts in JavaScript: a font swap driven by
 * a render pass flashes on every locale change and cannot work in a static export or in
 * a printed page, and the public dashboard is printed.
 */
export const FONT_STACKS = {
  latin: "'Instrument Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
  sinhala: "'Noto Sans Sinhala', 'Iskoola Pota', sans-serif",
  tamil: "'Noto Sans Tamil', 'Latha', sans-serif",
  /**
   * Every datum: reference codes, LKR amounts, coordinates, timestamps, hashes, GN
   * codes. Functional, not stylistic - amounts have to align down a column and a hash has
   * to be scannable character by character. Tabular figures are switched on with
   * `font-variant-numeric` wherever this stack is used.
   */
  mono: "'IBM Plex Mono', ui-monospace, 'Cascadia Mono', 'Source Code Pro', monospace",
} as const;

/**
 * The composite stack.
 *
 * The Sinhala and Tamil faces come after the Latin one rather than instead of it: a
 * Sinhala string routinely contains Latin digits, a GN code or an English place name, and
 * the browser falls through per glyph. Ordering Latin first keeps those runs in the
 * interface face instead of in Noto's Latin, which is a different colour on the page.
 */
export const FONT_SANS =
  "'Instrument Sans', 'Noto Sans Sinhala', 'Noto Sans Tamil', system-ui, " +
  "-apple-system, 'Segoe UI', 'Iskoola Pota', 'Latha', sans-serif";

/**
 * The type scale, in px. 12 / 13 / 14 / 16 / 20 / 26 / 34 / 44.
 *
 * Nothing below 13px renders on a mobile surface, ever - a GN officer is reading this in
 * rain with wet hands, on a mid-range Android, and 12px is reserved for dense desktop
 * chrome (table column headers, the time spine's tick labels) where the reader is sitting
 * at a desk. `MIN_MOBILE_SIZE` is the number the mobile lint rule checks against.
 */
export const TYPE_SCALE = {
  '2xs': 12,
  xs: 13,
  sm: 14,
  base: 16,
  lg: 20,
  xl: 26,
  '2xl': 34,
  '3xl': 44,
} as const;

export type TypeSize = keyof typeof TYPE_SCALE;

export const MIN_MOBILE_SIZE = 13;

/** Latin line heights, as unitless multipliers. Tighter as the size grows, as usual. */
export const LINE_HEIGHTS: Record<TypeSize, number> = {
  '2xs': 1.5,
  xs: 1.5,
  sm: 1.5,
  base: 1.55,
  lg: 1.4,
  xl: 1.3,
  '2xl': 1.2,
  '3xl': 1.1,
};

/**
 * Per-script metric overrides.
 *
 * `lineHeightDelta` is added to the Latin multiplier and `sizeScale` multiplies the
 * computed px size at body sizes and below. Both are what it took for a paragraph of
 * Sinhala, one of Tamil and one of English to read at the same optical weight when set
 * side by side.
 *
 * Sinhala takes the larger leading: its ascender/descender range is the widest of the
 * three and at Latin leading the ේ of one line touches the ු of the line above. Tamil is
 * denser horizontally but shallower vertically, so it needs less leading and a slightly
 * larger size to match Latin's x-height.
 *
 * The size uplift stops above `base`. At display sizes the scripts already match, and
 * scaling a 44px headline by 1.04 pushes a three-word Tamil title onto a second line.
 */
export interface ScriptMetrics {
  readonly stack: string;
  readonly lineHeightDelta: number;
  readonly sizeScale: number;
}

export const SCRIPT_METRICS: Record<Locale, ScriptMetrics> = {
  en: { stack: FONT_STACKS.latin, lineHeightDelta: 0, sizeScale: 1 },
  si: { stack: FONT_STACKS.sinhala, lineHeightDelta: 0.15, sizeScale: 1.06 },
  ta: { stack: FONT_STACKS.tamil, lineHeightDelta: 0.12, sizeScale: 1.04 },
};

/** Sizes at and below which the per-script uplift applies. */
const UPLIFTED: readonly TypeSize[] = ['2xs', 'xs', 'sm', 'base'] as const;

/** The rendered px size for one size step in one locale. */
export function sizeFor(size: TypeSize, locale: Locale): number {
  const base = TYPE_SCALE[size];
  if (!UPLIFTED.includes(size)) return base;
  // Rounded to a whole pixel: a fractional font-size renders differently across the
  // three browser engines this has to look identical in.
  return Math.round(base * SCRIPT_METRICS[locale].sizeScale);
}

/** The rendered line-height multiplier for one size step in one locale. */
export function lineHeightFor(size: TypeSize, locale: Locale): number {
  const delta = SCRIPT_METRICS[locale].lineHeightDelta;
  // Display sizes get half the delta. At 34px and up the leading is already generous in
  // absolute terms and the full delta opens a visible gap between headline lines.
  const scale = UPLIFTED.includes(size) ? 1 : 0.5;
  return Number((LINE_HEIGHTS[size] + delta * scale).toFixed(3));
}

export const FONT_WEIGHTS = {
  regular: 400,
  medium: 500,
  semibold: 600,
} as const;

/**
 * Tracking. Negative on display sizes only.
 *
 * Never applied to Sinhala or Tamil: both are cursive-adjacent scripts whose glyphs join
 * and stack, and letter-spacing breaks the join. The CSS output scopes this to
 * `:lang(en)` for that reason.
 */
export const LETTER_SPACING: Partial<Record<TypeSize, string>> = {
  '2xl': '-0.01em',
  '3xl': '-0.02em',
};
