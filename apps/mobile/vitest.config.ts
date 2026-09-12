import { defineConfig } from 'vitest/config';

/**
 * Vitest over the offline core.
 *
 * `environment: node` and not jsdom: nothing under test here renders. The React Native
 * screens are thin and read their state from these modules, which is deliberate - the
 * rules that lose a household's assessment if they are wrong are all in plain TypeScript
 * and are tested against a real SQLite engine (`test-support/node-database.ts`) rather
 * than through an emulator.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'test/**/*.test.ts'],
  },
});
