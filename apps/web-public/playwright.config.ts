/**
 * Browser tests for the public dashboard.
 *
 * Four suites run here rather than in jsdom, and each for a reason jsdom cannot satisfy:
 *
 * - **`pii-sweep`** reads the bytes the server actually sent. That is the whole assertion —
 *   the SQL and the response models are promises about intent, and this is the check that
 *   looks at the output.
 * - **`no-js`** needs a browser with scripting genuinely off. `context({ javaScriptEnabled:
 *   false })` does that; nothing in a Node test runner can.
 * - **`a11y`** runs axe against real rendered HTML with real CSS. web-ops runs axe in jsdom
 *   because its screens are client components it can mount; every page here is an async
 *   server component, and rendering one outside a Next server is not something jsdom does.
 * - **`layout`** is the overflow gate over every route in all three scripts, which is a
 *   measurement of real layout.
 *
 * **Two servers, and the order matters.** `next dev` is pointed at the stub through the same
 * environment variables the deployment uses, so the suite exercises the real server-side
 * fetch path. Playwright starts them in array order and waits for each, so the stub is
 * listening before Next tries to prerender anything against it.
 */

import { defineConfig, devices } from '@playwright/test';

const PORT = 3101;
const STUB_PORT = 8099;
const BASE_URL = `http://127.0.0.1:${PORT}`;
const STUB_URL = `http://127.0.0.1:${STUB_PORT}`;

export default defineConfig({
  testDir: './e2e',
  // A privacy gate that is flaky is a privacy gate nobody trusts, and a retry would hide it.
  retries: 0,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    // A cheap Android in portrait. The brief names this reader explicitly, and it is the
    // width the overflow gate is meaningful at — a 1440px viewport hides every overflow
    // this suite exists to catch.
    viewport: { width: 390, height: 844 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `node ./e2e/stub-services.mjs`,
      url: `${STUB_URL}/api/v1/public/funnel`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: { SARANA_STUB_PORT: String(STUB_PORT) },
    },
    {
      /**
       * A production build, not `next dev`, and the PII sweep is why.
       *
       * The sweep's whole claim is that it reads the bytes the site actually publishes. A
       * development server does not publish those bytes: it inlines every module's file
       * path into the RSC payload for hot reload, so the first run reported forty findings
       * per page — all of them pnpm paths like `next@15.5.24_@babel+core@7.29.7_` matching
       * the email pattern, and none of them anything the app had written. A sweep whose
       * signal is buried under its own harness is a sweep somebody switches off.
       *
       * It also makes the other three suites measure the real thing: the layout gate runs
       * against production CSS, and the axe sweep against the markup that ships.
       *
       * The cost is a build on every run. `build:local` skips the standalone trace-copy
       * step, which is the slow part and the part Windows refuses without Developer Mode.
       */
      // The port is passed as `PORT`, which `next start` honours, rather than as an
      // argument. `pnpm run start:local -- --port 3101` puts the flag where pnpm's
      // argument forwarding mangles it on Windows, and `next start` then reads `--port`
      // as the project directory and refuses to boot.
      command: `pnpm run build:local && pnpm run start:local`,
      url: `${BASE_URL}/en`,
      /**
       * Never reused, unlike the stub beside it.
       *
       * `reuseExistingServer` is the right default for a `next dev` harness and the wrong
       * one here, because this server holds an **ISR cache**. A server left running from an
       * earlier invocation keeps serving pages it prerendered then; if the stub it was built
       * against has since been restarted, the five-minute revalidation regenerates them
       * against nothing and caches the "figure unavailable" page instead.
       *
       * That is exactly what happened while this suite was being written: every file passed
       * on its own and three failed when run together, because the shared server had
       * revalidated into failure pages between them. A stale build silently under test is a
       * worse outcome than a slow one, and refusing the port is a loud failure.
       */
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        PORT: String(PORT),
        SARANA_CORE_API_URL: STUB_URL,
        SARANA_ALERTING_SVC_URL: STUB_URL,
        SARANA_LEDGER_SVC_URL: STUB_URL,
      },
    },
  ],
});
