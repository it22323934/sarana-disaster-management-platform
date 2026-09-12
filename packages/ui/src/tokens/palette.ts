/**
 * The interface palette. Cool, so it can never be mistaken for a severity signal.
 *
 * The one rule this file exists to enforce: the warm end of the spectrum belongs to
 * hazard severity and to nothing else. No button, link, chart series, chrome element or
 * decoration in SARANA is warm. An operator who sees an orange element on this platform
 * is looking at a watch-level hazard, every time, without having to check.
 *
 * Values marked "brief" are taken verbatim from the design brief. Values marked
 * "derived" were added because a brief value did not meet its own accessibility floor in
 * the role the brief assigned it; each carries the measurement that forced it.
 */

import type { Hex } from './contrast.js';

/** Which base surface a colour is being rendered on. Not a user preference - a context. */
export type Surface = 'dark' | 'light';

export const INK = {
  /** brief - ops console base */
  900: '#0B1220',
  /** brief - raised surface */
  800: '#121A2A',
  /** brief - card */
  700: '#1C2739',
  /** brief - hairline / divider */
  600: '#2A3548',
  /** brief - secondary text on dark */
  300: '#94A3B8',
  /** brief - primary text on dark */
  50: '#E8EDF5',
} as const satisfies Record<number, Hex>;

export const PAPER = {
  /** brief - public dashboard base */
  50: '#FBFCFD',
  /** brief - raised surface on light */
  100: '#F1F4F8',
  /** brief - primary text on light */
  900: '#101720',
} as const satisfies Record<number, Hex>;

/**
 * The interface accent. Azure, at hue 205.
 *
 * The brief specified a teal ramp (`#0E7C86` and its neighbours). It was moved to azure
 * because teal reads as a product colour and this is a government transparency surface;
 * blue is the register the audience already associates with a public record. The move is
 * along the cool axis, so the rule this file exists to enforce is untouched - azure is
 * further from the severity ramp than the teal it replaces, not closer.
 *
 * Every value below was solved for rather than chosen by eye. The ramp has to satisfy
 * nine pairings at once, and two of them pull against each other: `--signal-400` must
 * clear 4.5:1 as accent text on all three dark surfaces, while white on `--signal-400`
 * must stay *below* 4.5:1 so the hover rule below still means something. Hues past ~220
 * have no solution at all - the window closes - which is why this is azure and not
 * indigo. Worst-case headroom across the nine is +1.09.
 */
export const SIGNAL = {
  /**
   * derived - the primary action darkens on hover, it does not lighten.
   *
   * The brief names `--signal-400` as the hover state. White on `--signal-400` is
   * 2.35:1 and a hover state is not exempt from SC 1.4.3, so a button that lightened
   * would drop its own label below AA at the moment the pointer was on it.
   * `--signal-400` keeps its other role - the accent, link and focus colour on the dark
   * base, where it is measured against `--ink-900`/`--ink-800`/`--ink-700` and passes.
   */
  600: '#0B5284',
  /** primary action. White on it is 5.80:1. */
  500: '#0E69AA',
  /** accent and focus on dark; hover only where it is not carrying white text */
  400: '#52A5E0',
  /**
   * derived - text on the `--signal-100` tint.
   *
   * The tint is a real surface in this system (selected rows, the active filter chip),
   * so it needs a text colour that clears AA on it rather than one that nearly does.
   * This pairing measures 8.04:1.
   */
  700: '#094671',
  /** tint */
  100: '#DBEAF5',
} as const satisfies Record<number, Hex>;

export const VERIFY = {
  /** brief - verified / confirmed / chain-valid */
  500: '#2F6F4E',
  /**
   * derived - the same role on the dark base.
   *
   * `--verify-500` on `--ink-900` is 3.12:1. A green tick against a dark operations
   * console is text, not decoration, so it needed lifting to clear AA on the darkest
   * three surfaces rather than only on the light one.
   */
  400: '#45A272',
} as const satisfies Record<number, Hex>;

/**
 * The "a human must act" colour, and it is spent on nothing else.
 *
 * Both mandatory gates - committing a life-safety dispatch, releasing a disbursement -
 * and their pending states use this and only this. It becomes a colour an operator
 * learns to scan a screen for. Every additional place it appears makes that scan
 * slower, so there are no additional places.
 */
export const PENDING = {
  /** brief - awaiting human */
  500: '#5B6B8C',
  /** derived - `--pending-500` on `--ink-900` is 3.50:1; same reasoning as `--verify-400` */
  400: '#8492AF',
} as const satisfies Record<number, Hex>;

/** Text on a saturated fill. Not pure white: it haloes against deep red at 3am. */
export const ON_FILL: Hex = '#FFECEC';

/** Text on a cool saturated fill (the primary button, the pending banner). */
export const ON_SIGNAL: Hex = '#FFFFFF';

/**
 * The focus ring is a token, not a colour.
 *
 * The brief specifies a 2px `--signal-400` ring. On `--paper-100`, the light base's
 * raised surface, that measures 2.44:1 - under the 3:1 floor SC 1.4.11 sets for a
 * non-text indicator, and a focus ring is the one indicator a keyboard-only dispatcher
 * cannot work without. Resolving it per surface keeps the brief's ring on dark, where it
 * passes comfortably, and steps down to `--signal-500` on light, where it does not.
 *
 * The azure ramp did not rescue this one. `--signal-400` is a lighter value than the teal
 * it replaced, so the light-surface ring got further from the floor rather than closer,
 * and the per-surface split is load-bearing exactly as before.
 */
export const FOCUS_RING: Record<Surface, Hex> = {
  dark: SIGNAL[400],
  light: SIGNAL[500],
};

/**
 * The accent as *text* - links, active tab labels, the selected filter.
 *
 * Not the same value as the accent as a *fill*. Under the teal ramp this split was forced:
 * `--signal-500` measured 4.48:1 on `--paper-100`, so a link inside a card missed AA by
 * two hundredths while the same link on the page background passed.
 *
 * **Azure removed that constraint and the split stays anyway.** `--signal-500` now
 * measures 5.65:1 on `--paper-50` and 5.26:1 on `--paper-100`, so collapsing the two roles
 * would pass the gate. It is kept because the gate is a floor, not a target: this is a
 * dashboard read on phones in daylight and printed in offices, and a link that clears AA
 * by a hundredth in a lab clears nothing on a sunlit screen. `--signal-500` stays the
 * button fill (white on it is 5.80:1) and the light theme reads its accent text one step
 * darker, at 8.00:1.
 */
export const TEXT_ACCENT: Record<Surface, Hex> = {
  dark: SIGNAL[400],
  light: SIGNAL[600],
};

/** Base and raised surfaces per theme, in the order a card stack uses them. */
export const SURFACES: Record<Surface, { base: Hex; raised: Hex; card: Hex; text: Hex; muted: Hex }> =
  {
    dark: { base: INK[900], raised: INK[800], card: INK[700], text: INK[50], muted: INK[300] },
    // The light theme has no third level: a public dashboard that is read in daylight
    // and printed gets no benefit from a card shade a printer will render as white.
    light: {
      base: PAPER[50],
      raised: PAPER[100],
      card: PAPER[100],
      text: PAPER[900],
      muted: '#4A5A70',
    },
  };

/** Hairlines and dividers. Deliberately quiet - see the exemption in `pairings.ts`. */
export const DIVIDER: Record<Surface, Hex> = { dark: INK[600], light: '#D9E0EA' };
