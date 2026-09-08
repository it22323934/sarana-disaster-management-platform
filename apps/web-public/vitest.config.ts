/**
 * Unit tests for the public dashboard.
 *
 * `node` rather than jsdom, and that is a consequence of the app's design rather than a
 * shortcut. Every page here is an async server component; there is nothing to mount in a
 * fake DOM and no interactive behaviour to drive. What these tests cover is the pure
 * modules — the PII battery, the formatters, the choropleth scale, the ISR literals — and
 * the rendered output is covered where it actually renders, in `e2e/` against a real
 * browser and a real server.
 *
 * The `.js` alias mirrors the one in `next.config.ts`: the workspace packages are ESM and
 * import each other with the extension TypeScript's ESM output requires, which Vite
 * resolves natively for source but not across a package boundary without help.
 */

import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
  },
  test: {
    environment: 'node',
    globals: false,
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**'],
  },
});
