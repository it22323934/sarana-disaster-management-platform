/**
 * The axe sweep over the console's screens.
 *
 * Separate config because it renders whole screens in all three locales and is slow
 * enough that running it on every save would stop people running the fast suite.
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
    testTimeout: 30_000,
  },
});
