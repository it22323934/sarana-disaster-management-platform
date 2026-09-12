/**
 * The SARANA design system.
 *
 * One system across the operations console, the public dashboard and both mobile
 * surfaces. It has to work at 3am in an operations room, in the rain on a mid-range
 * Android, and in a newsroom on a laptop, in three scripts, at equal quality.
 *
 * Two rules run through all of it:
 *
 *   Colour means severity, and nothing else. Every interface accent is cool, so a
 *   coloured element can never be mistaken for a hazard signal.
 *
 *   Trilingual or it does not ship. `LocalisedText` cannot render a bare string, and
 *   every component that shows citizen-facing text takes all three locales or refuses.
 *
 * `tokens.css` and `tokens.nativewind.js` are generated from `src/tokens` and must be
 * imported by the consuming app; the components read CSS custom properties and will
 * render unstyled without them.
 */

export * from './tokens/index.js';
export * from './primitives/index.js';
export * from './data/index.js';
export * from './domain/index.js';
export * from './map/index.js';
export * from './forms/index.js';
export { cn } from './lib/cn.js';
export { DISABLED, FOCUS_RING, TOUCH_TARGET } from './lib/focus.js';

// The badge shipped before the design system existed. Kept as a named re-export of
// MockDataBadge so the scaffolded pages in both web apps keep compiling; new code uses
// MockDataBadge directly.
export { MockDataBadge as SimulatedDataBadge } from './domain/trust.js';
export type { MockDataBadgeProps as SimulatedDataBadgeProps } from './domain/trust.js';
