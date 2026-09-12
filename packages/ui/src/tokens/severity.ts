/**
 * The severity ramp. Reserved: nothing that is not a hazard severity uses these.
 *
 * The five base hexes are the brief's, unchanged. They are *identity* colours - what the
 * level looks like as a marker on a map or a rule down the side of a card - and they are
 * deliberately not text colours. Measured against the two base surfaces they land like
 * this:
 *
 *     level  base       on --ink-900   on --paper-50
 *     0      #4A5568         2.49            7.33
 *     1      #C9A227         7.74            2.36
 *     2      #D97706         5.88            3.10
 *     3      #DC2626         3.88            4.70
 *     4      #7F1D1D         1.87            9.75
 *
 * Every one of them fails AA as body text on one surface or the other, and levels 0-3
 * fail on the dark base which is where the console actually runs. So each level carries a
 * derived `bg`/`fg`/`border` triple per surface, and the raw hue is kept for the marker.
 * The derivation held `fg` to 4.75:1 on its own `bg` (headroom above the 4.5 floor so a
 * rounding change can never silently drop the gate) and `border` to 3.2:1 against the
 * *tightest* surface the chip can sit on - `--ink-700` on dark and `--paper-100` on
 * light. Solving the light borders against `--paper-50` instead, which is the obvious
 * thing to do, put all four of them at 2.98:1 on a card and the gate caught it.
 *
 * `tests/tokens/contrast.test.ts` and `pnpm test:contrast` re-measure all of it. If you
 * change a hex here and do not change it there, CI tells you which pairing you broke.
 */

import type { Hex } from './contrast.js';
import { ON_FILL, type Surface } from './palette.js';

/** CAP 1.2 severity, as the platform grades it. `4` is the evacuate line. */
export type SeverityLevel = 0 | 1 | 2 | 3 | 4;

export const SEVERITY_LEVELS: readonly SeverityLevel[] = [0, 1, 2, 3, 4] as const;

/**
 * The silhouette carried by every severity element.
 *
 * Roughly 8% of men have a colour vision deficiency, and the person reading a warning at
 * 3am may be one of them - so no severity is ever encoded by colour alone. These five are
 * chosen to stay distinct in monochrome at 12px, which rules out the obvious
 * outline-triangle/filled-triangle pairing: at that size the fill is the only difference
 * and it disappears first.
 */
export type SeverityShape = 'circle' | 'square' | 'triangle' | 'diamond' | 'octagon';

export interface SeverityVariant {
  /** Chip background on this surface. */
  readonly bg: Hex;
  /** Text on `bg`. Holds 4.5:1 against it. */
  readonly fg: Hex;
  /** Chip boundary. Holds 3:1 against the surface the chip sits on, not against `bg`. */
  readonly border: Hex;
}

export interface SeverityToken {
  readonly level: SeverityLevel;
  /** Stable machine name. Used in CSS variable names and in `data-severity`. */
  readonly name: 'none' | 'advisory' | 'watch' | 'warning' | 'severe';
  /** The identity colour from the brief. A marker and a rule, never body text. */
  readonly base: Hex;
  readonly shape: SeverityShape;
  readonly dark: SeverityVariant;
  readonly light: SeverityVariant;
}

/**
 * Level 4 is a fill on both surfaces; levels 0-3 are tints.
 *
 * Level 3 (#DC2626) and level 4 (#7F1D1D) are the same hue and differ only in
 * saturation and lightness. Lightening level 4 far enough to read as text on the dark
 * base lands it within a few percent of a lightened level 3 - so the two loudest levels
 * would become the hardest pair on the ramp to tell apart, which is exactly the wrong way
 * round. Filling level 4 instead makes it the only chip on the screen with inverted
 * weight: discriminable without colour, without shape, and at a glance across a room.
 */
export const SEVERITY: Record<SeverityLevel, SeverityToken> = {
  0: {
    level: 0,
    name: 'none',
    base: '#4A5568',
    shape: 'circle',
    dark: { bg: '#21262E', fg: '#8491A8', border: '#66758F' },
    light: { bg: '#E9EBEF', fg: '#4F6790', border: '#7A88A0' },
  },
  1: {
    level: 1,
    name: 'advisory',
    base: '#C9A227',
    shape: 'square',
    dark: { bg: '#372F19', fg: '#BB9724', border: '#897228' },
    light: { bg: '#F7F2E0', fg: '#82670F', border: '#A28322' },
  },
  2: {
    level: 2,
    name: 'watch',
    base: '#D97706',
    shape: 'triangle',
    dark: { bg: '#372919', fg: '#DB8118', border: '#9D692E' },
    light: { bg: '#F7EDE0', fg: '#9E5604', border: '#BC7728' },
  },
  3: {
    level: 3,
    name: 'warning',
    base: '#DC2626',
    shape: 'diamond',
    dark: { bg: '#371919', fg: '#E66262', border: '#CA4747' },
    light: { bg: '#F7E0E0', fg: '#C61111', border: '#DD5E5E' },
  },
  4: {
    level: 4,
    name: 'severe',
    base: '#7F1D1D',
    shape: 'octagon',
    // The fill is the base hue itself on both surfaces. On dark the border lifts so the
    // chip's edge separates from the card; on light it drops so the edge reads at all.
    dark: { bg: '#7F1D1D', fg: ON_FILL, border: '#BD5252' },
    light: { bg: '#7F1D1D', fg: ON_FILL, border: '#5F1616' },
  },
};

export function severityVariant(level: SeverityLevel, surface: Surface): SeverityVariant {
  return SEVERITY[level][surface];
}

/**
 * The label every severity element carries alongside its colour and its shape.
 *
 * Trilingual because a citizen-facing string in fewer than three languages does not ship,
 * and these reach the public dashboard. The wording matches the alerting service's CAP
 * severity vocabulary rather than paraphrasing it - an operator reads the same word here
 * and in the alert they are about to sign.
 */
export const SEVERITY_LABELS: Record<SeverityLevel, { si: string; ta: string; en: string }> = {
  0: { si: 'තොරතුරු', ta: 'தகவல்', en: 'Information' },
  1: { si: 'උපදේශනය', ta: 'அறிவுரை', en: 'Advisory' },
  2: { si: 'අවධානය', ta: 'கண்காணிப்பு', en: 'Watch' },
  3: { si: 'අනතුරු ඇඟවීම', ta: 'எச்சரிக்கை', en: 'Warning' },
  4: { si: 'ඉවත් වන්න', ta: 'வெளியேறுங்கள்', en: 'Evacuate' },
};
