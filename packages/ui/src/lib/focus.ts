/**
 * The focus ring, in one place.
 *
 * The ops console has to be fully operable from the keyboard - a dispatcher with a
 * trackpad and wet hands is a real scenario, and so is one whose mouse is somewhere
 * under a pile of printouts. Every interactive element in this library composes this
 * string, so there is exactly one definition of what focus looks like and no component
 * can quietly drop it.
 *
 * `focus-visible` rather than `focus`: a ring that appears on a mouse click is noise
 * that trains people to ignore rings.
 */

export const FOCUS_RING =
  'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 ' +
  'focus-visible:outline-[var(--focus-ring)]';

/**
 * The minimum hit area, applied to every control that is not inside a data-dense table.
 *
 * WCAG 2.2 SC 2.5.8 puts the floor at 24x24 CSS px; this system uses 44x44, which is the
 * figure the mobile guidelines have used for a decade and the one a wet finger needs.
 */
export const TOUCH_TARGET = 'min-h-[var(--touch-target-min)] min-w-[var(--touch-target-min)]';

/** Disabled styling. Never `pointer-events-none` alone - that hides the reason from AT. */
export const DISABLED = 'disabled:cursor-not-allowed disabled:opacity-50';
