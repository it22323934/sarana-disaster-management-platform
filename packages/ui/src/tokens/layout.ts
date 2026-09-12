/**
 * Spacing, radius, motion and the touch-target floor.
 *
 * Small file, but every number in it is a decision that shows up in a usability
 * complaint if it is wrong.
 */

/** 4px base scale. Every margin, padding and gap in the system is a multiple of this. */
export const SPACE_BASE = 4;

export const SPACE = {
  0: 0,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
} as const;

export const RADIUS = {
  /** Data cells. Nearly square, so a column of them reads as a grid rather than as pills. */
  cell: 2,
  /** The default. Cards, inputs, buttons. */
  default: 6,
  /** Sheets and dialogs, where the corner is large enough to be seen as a corner. */
  surface: 10,
  /** Status pills and the severity chip. */
  full: 9999,
} as const;

/**
 * Motion durations, in ms.
 *
 * Motion in this product means "something changed that you need to notice". There is no
 * decorative animation anywhere: no entrance transition on a page, no easing on a number
 * that ticks up, nothing that moves because movement is pleasant. During an incident an
 * operator's attention is the scarcest resource on the platform and spending it on a
 * fade is indefensible.
 */
export const MOTION = {
  /** A state change on an element already on screen: a toggle, a row selection. */
  state: 120,
  /** A surface arriving or leaving: a sheet, a dialog, a toast. */
  surface: 200,
} as const;

export const EASING = {
  /** Arriving. Decelerates into place. */
  enter: 'cubic-bezier(0.16, 1, 0.3, 1)',
  /** Leaving. Linear-ish, because a slow exit reads as lag. */
  exit: 'cubic-bezier(0.4, 0, 1, 1)',
} as const;

/**
 * `prefers-reduced-motion` disables all of it, with nothing lost.
 *
 * Nothing in this system is load-bearing motion - no meaning is carried only by a
 * transition - so the reduced-motion branch is a straight `duration: 0`, not a
 * substitute animation.
 */
export const REDUCED_MOTION_DURATION = 0;

/** WCAG 2.2 SC 2.5.8 target size, in px. */
export const TOUCH_TARGET_MIN = 44;

/**
 * The citizen SOS button.
 *
 * Larger than the floor because it is pressed one-handed, in the dark, possibly while
 * moving, by someone who is frightened. The extra 12px is the difference between a
 * deliberate press and a missed one.
 */
export const TOUCH_TARGET_SOS = 56;

/** Focus ring geometry. The colour is `FOCUS_RING` in `palette.ts` and is per-surface. */
export const FOCUS_RING_WIDTH = 2;
export const FOCUS_RING_OFFSET = 2;

/** Elevation. Two levels only - a deeper stack is a sign the layout is wrong. */
export const SHADOW = {
  raised: '0 1px 2px rgb(0 0 0 / 0.20)',
  overlay: '0 12px 32px rgb(0 0 0 / 0.35)',
} as const;

/** The z-order every overlay in the system agrees on. */
export const Z_INDEX = {
  spine: 20,
  sticky: 30,
  overlay: 40,
  dialog: 50,
  toast: 60,
} as const;
