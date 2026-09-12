/**
 * The width budgets the i18n overflow gate measures against.
 *
 * Each entry is a real slot in a real component, with the width that slot actually gets
 * in the app, and the string that has to fit inside it in all three scripts.
 *
 * **This is a width model, not a browser.** jsdom has no layout, so the gate estimates
 * rendered width from character count, a per-script average advance, and the per-script
 * size uplift from the type scale. That model catches exactly the regression it is built
 * for - a translation growing past the space its slot allows - and it does not catch a
 * layout that breaks for some other reason. A real pixel measurement needs a browser, and
 * that is a Playwright job for the visual regression suite, which is out of scope here
 * and named in the handoff as such.
 *
 * The advances below were measured from Noto Sans, Noto Sans Sinhala and Noto Sans Tamil
 * at 16px over the seeded strings in `packages/ts-shared/src/i18n/locales/*.json`, taking
 * the mean advance per code point. They are averages over real UI copy, not over lorem,
 * which matters: Sinhala UI strings are short and dense, and an average taken over a
 * paragraph of prose reads differently.
 */

import type { Locale, LocalisedText } from '@sarana/ts-shared/i18n';

import { SCRIPT_METRICS, TYPE_SCALE, type TypeSize } from '../tokens/typography.js';
import { LONGEST_LABELS, UI_STRINGS } from './fixtures.js';

/**
 * Mean advance width per code point, as a fraction of the font size.
 *
 * Sinhala is the widest: its glyphs carry more vertical furniture and the base consonants
 * are wider than Latin lowercase. Tamil sits between the two.
 */
export const MEAN_ADVANCE: Record<Locale, number> = {
  en: 0.5,
  si: 0.62,
  ta: 0.58,
};

export interface OverflowSlot {
  /** Where this renders. Printed on failure, so make it locate the component. */
  readonly name: string;
  readonly text: LocalisedText;
  /** The slot's inner width in px, after padding. */
  readonly budgetPx: number;
  readonly size: TypeSize;
  /**
   * How many lines the slot can take before it breaks its container.
   *
   * 1 for anything on a single line - a button label, a table header, a pill. Above 1 for
   * blocks that are allowed to wrap.
   */
  readonly lines: number;
}

/**
 * Estimated rendered width of a string, in px.
 *
 * Uses the same per-script size uplift the CSS applies, so a 14px Tamil label is measured
 * at the 15px it actually renders at rather than at its nominal size.
 */
export function estimateWidthPx(text: string, locale: Locale, size: TypeSize): number {
  const nominal = TYPE_SCALE[size];
  const rendered = nominal * (size === '2xl' || size === '3xl' ? 1 : SCRIPT_METRICS[locale].sizeScale);
  // Code points rather than UTF-16 units: Sinhala and Tamil use combining marks freely,
  // and `String.length` counts a two-unit grapheme twice.
  const codePoints = [...text].length;
  return codePoints * MEAN_ADVANCE[locale] * rendered;
}

export interface OverflowResult {
  readonly slot: string;
  readonly locale: Locale;
  readonly text: string;
  readonly estimatedPx: number;
  readonly availablePx: number;
  readonly fits: boolean;
}

export function measure(slot: OverflowSlot, locale: Locale): OverflowResult {
  const estimatedPx = estimateWidthPx(slot.text[locale], locale, slot.size);
  const availablePx = slot.budgetPx * slot.lines;
  return {
    slot: slot.name,
    locale,
    text: slot.text[locale],
    estimatedPx: Math.round(estimatedPx),
    availablePx,
    fits: estimatedPx <= availablePx,
  };
}

/**
 * The slots under gate.
 *
 * Widths come from the components' own stories, which use the widths the apps give them:
 * a 320px column in the console sidebar, a 260px stat tile, a 420px gate banner.
 */
export const OVERFLOW_SLOTS: readonly OverflowSlot[] = [
  {
    name: 'Button (primary) label in a 320px column',
    text: LONGEST_LABELS.buttonPrimary!,
    // 320px column, minus the 3px story padding either side and the button's 16px
    // horizontal padding either side.
    budgetPx: 320 - 6 - 32,
    size: 'sm',
    lines: 1,
  },
  {
    name: 'PendingGateBanner title in a 420px banner',
    text: LONGEST_LABELS.gateTitle!,
    // The banner's title column shares the row with the mark and the action button.
    budgetPx: 420 - 16 - 24 - 120,
    size: 'sm',
    lines: 2,
  },
  {
    name: 'StatCard label in a 260px tile',
    text: LONGEST_LABELS.statLabel!,
    budgetPx: 260 - 32,
    size: '2xs',
    lines: 2,
  },
  {
    name: 'Admin level label in a table header',
    text: LONGEST_LABELS.adminLevel!,
    budgetPx: 180,
    size: '2xs',
    lines: 2,
  },
  {
    name: 'ConfidenceMeter consequence line',
    text: LONGEST_LABELS.confidenceConsequence!,
    budgetPx: 380 - 24,
    size: '2xs',
    lines: 2,
  },
  {
    name: 'OfflineIndicator queued count',
    text: LONGEST_LABELS.offlineQueued!,
    budgetPx: 380 - 24 - 40,
    size: '2xs',
    lines: 1,
  },
  {
    name: 'EmptyState title',
    text: LONGEST_LABELS.emptyTitle!,
    budgetPx: 360 - 48,
    size: 'base',
    lines: 2,
  },
  {
    name: 'EmptyState description',
    text: LONGEST_LABELS.emptyDescription!,
    budgetPx: 360 - 48,
    size: 'sm',
    lines: 4,
  },
  {
    name: 'TranslationCompleteness label',
    text: LONGEST_LABELS.translationIncomplete!,
    budgetPx: 240,
    size: '2xs',
    lines: 1,
  },
  {
    name: 'MockDataBadge source',
    text: LONGEST_LABELS.simulatedSource!,
    budgetPx: 380 - 24 - 90,
    size: '2xs',
    lines: 1,
  },
  {
    name: 'LanguageSwitcher segment',
    text: UI_STRINGS.language!,
    budgetPx: 100,
    size: 'sm',
    lines: 1,
  },
  {
    name: 'Tab label in a 420px strip (two tabs)',
    text: UI_STRINGS.incidentQueue!,
    budgetPx: 420 / 2 - 32,
    size: 'sm',
    lines: 1,
  },
  {
    name: 'Pagination button label',
    text: UI_STRINGS.previous!,
    budgetPx: 120 - 24,
    size: 'xs',
    lines: 1,
  },
  {
    name: 'TimeSpine phase label (compact, 360px)',
    text: UI_STRINGS.recovery!,
    budgetPx: 360 - 16 - 60 - 110,
    size: 'xs',
    lines: 1,
  },
  {
    name: 'ImpactClassBadge prefix',
    text: UI_STRINGS.predictedImpact!,
    budgetPx: 320 - 24 - 80,
    size: '2xs',
    lines: 1,
  },
];
