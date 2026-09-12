/**
 * The single source of truth for every SARANA design token.
 *
 * `tokens.css` and `tokens.nativewind.js` at the package root are generated from this
 * module by `scripts/generate-tokens.ts`. They are committed so an app can import them
 * without a build step, and `pnpm test:tokens-sync` regenerates and diffs them, so an
 * edit here that is not regenerated fails CI rather than shipping three token tables
 * that disagree.
 */

export * from './contrast.js';
export * from './palette.js';
export * from './severity.js';
export * from './typography.js';
export * from './layout.js';
export * from './pairings.js';
