/**
 * Unit and component tests.
 *
 * jsdom rather than happy-dom: Radix's primitives lean on focus management, pointer
 * capture and `matchMedia`, and jsdom is the environment their own suite runs in. A
 * faster DOM that disagrees about focus would produce green tests for keyboard
 * behaviour that does not work.
 */

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The a11y sweep has its own config: it walks the story catalogue rather than the
    // test files, and it is slower, so it is not part of the inner loop.
    exclude: ['src/**/*.a11y.test.tsx', 'node_modules/**'],
  },
});
