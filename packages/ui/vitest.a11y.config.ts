/**
 * The axe sweep. `pnpm --filter @sarana/ui test:a11y`.
 *
 * Separate from the unit config because it walks every exported story in the catalogue
 * rather than a list of test files, and because it is slow enough that running it on
 * every save would stop people running the fast suite.
 */

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.a11y.test.tsx'],
    // Rendering every story through axe takes longer than the 5s default on a cold run.
    testTimeout: 30_000,
  },
});
