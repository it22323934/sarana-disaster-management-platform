/**
 * The part of the design system that costs a page no JavaScript.
 *
 * Everything re-exported here is a pure renderer: no hook, no browser API, no function
 * prop, and no import that reaches a module carrying `'use client'`. A React Server
 * Component can import from this entry point and ship nothing to the browser.
 *
 * **Why this exists.** `@sarana/ui` is one barrel, and importing anything from it drags the
 * whole module graph in — including the twelve Radix-backed primitives. The public
 * dashboard's pages are entirely server components and its header needs exactly one
 * component from this library, `MockDataBadge`. Importing it from the root put **69 KB
 * gzipped of Radix** into every route of a site that renders no interactive control at all,
 * and pushed its initial JavaScript from comfortably inside the brief's 120 KB budget to
 * 186 KB.
 *
 * The badge could have been reimplemented in the app instead. That would have been worse:
 * it carries the trilingual "simulated data" strings, and a second copy is a second thing
 * to forget when the wording changes, on the one component whose whole job is to stop a
 * viewer believing the data is real.
 *
 * **The rule for adding to this file.** A module belongs here only if it has no
 * `'use client'` directive *and* nothing in its import graph does. `tokens.test.ts` asserts
 * that, so a component that later grows a `useState` cannot silently reintroduce the
 * client boundary into a server-rendered page — it fails the test instead.
 *
 * The console imports from the root as before. Nothing about this entry point changes what
 * that does.
 */

export {
  AuditTrail,
  ConfidenceMeter,
  MockDataBadge,
  OfflineIndicator,
  type AuditEntry,
  type AuditTrailProps,
  type ConfidenceBand,
  type ConfidenceMeterProps,
  type MockDataBadgeProps,
  type OfflineIndicatorProps,
} from './domain/trust.js';

export {
  ImpactClassBadge,
  SeverityDot,
  SeverityPill,
  SeverityShapeMark,
  type ImpactClassBadgeProps,
  type SeverityDotProps,
  type SeverityPillProps,
  type SeverityShapeMarkProps,
} from './domain/severity-pill.js';

export { Badge, type BadgeProps, type BadgeTone } from './primitives/badge.js';
export { Skeleton, type SkeletonProps } from './primitives/skeleton.js';

export { cn } from './lib/cn.js';

// Tokens are plain data and were always safe here. Re-exported so a server-only consumer
// needs one import rather than two.
export * from './tokens/index.js';
