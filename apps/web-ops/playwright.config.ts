/**
 * End-to-end configuration.
 *
 * The suite runs against `next dev` with the **gateway routes intercepted in the
 * browser**, not against a booted platform. That is a deliberate trade rather than a
 * shortcut: the flows these tests protect — the dispatch approval, its rejection, the
 * release and its refusal with an open grievance — are properties of the console, and
 * making them depend on six Docker services, a seeded Postgres and a working TOTP secret
 * would produce a suite that fails for reasons that have nothing to do with the console
 * and that nobody runs.
 *
 * What that means for what these tests can prove is stated in each file. The server-side
 * half of every gate is tested where it lives, in the Python suite, against a real
 * database.
 */

import { defineConfig, devices } from '@playwright/test';

const PORT = 3100;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  // A gate flow that is flaky is a gate flow nobody trusts; a retry would hide it.
  retries: 0,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    // The console has to work on a mid-range laptop in an operations room, not on a
    // 4K desktop. This is the resolution the three-pane layout is designed against.
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `pnpm exec next dev --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
