/**
 * Unit and component tests for the console.
 *
 * jsdom, and the same reasoning as the design system's config: Radix leans on focus
 * management and pointer capture, and a faster DOM that disagrees about focus would give
 * green tests for keyboard behaviour that does not work — on the one console that has to
 * be fully operable without a pointer.
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
    exclude: ['src/**/*.a11y.test.tsx', 'e2e/**', 'node_modules/**'],
  },
});
