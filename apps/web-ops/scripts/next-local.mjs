/**
 * `next build` or `next start` without the standalone server bundle.
 *
 *   pnpm --filter @sarana/web-ops build:local
 *   pnpm --filter @sarana/web-ops start:local
 *
 * The standalone bundle is the deployment artefact (ADR-010) and `pnpm build` still
 * produces it. It exists behind a flag because emitting it creates symlinks, which Windows
 * refuses without Developer Mode — after compilation and every static page have already
 * succeeded. Without a way to skip it, nothing could run `next start`, so nothing could
 * measure against a served production build: not the Lighthouse LCP assertion in file 20's
 * Definition of Done, and not anything else that needs the real bundle rather than dev.
 *
 * **`start` needs the same flag as `build`, which is the part that is easy to miss.**
 * `next start` re-reads `next.config.ts` in a fresh process, so a build made without the
 * standalone output and a start made with it disagree: the server warns that `next start`
 * does not work with `output: standalone` and then throws `Cannot find module
 * './chunks/…'` for the pages-router documents. The App Router still serves, so the
 * failure is a stream of errors in the log beside pages that look fine — which is exactly
 * the sort of thing that gets ignored until it is load-bearing. One script for both
 * commands is what keeps them in agreement.
 *
 * A script rather than an inline `VAR=x next …`, because that syntax is not portable to
 * the Windows shell this repository is developed on, and rather than a `cross-env`
 * dependency because spawning a child with one extra environment variable does not need
 * one.
 */

import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);

/**
 * The Next CLI entry point, resolved rather than looked up on PATH.
 *
 * `node_modules/.bin` is on PATH when a package script runs through pnpm and is not when
 * this file is invoked directly, so a bare `next` works in one case and fails with "not
 * recognized as an internal or external command" in the other. Resolving through the
 * module graph works in both, and it means the child can be spawned without `shell: true`
 * - which Node now warns about, because arguments through a shell are concatenated rather
 * than escaped.
 */
const NEXT_BIN = require.resolve('next/dist/bin/next');

const [command, ...rest] = process.argv.slice(2);

if (command !== 'build' && command !== 'start') {
  console.error(
    `Expected 'build' or 'start', got ${command ?? '(nothing)'}.\n` +
      'These are the two commands that have to agree about the standalone output.',
  );
  process.exit(1);
}

const result = spawnSync(process.execPath, [NEXT_BIN, command, ...rest], {
  cwd: ROOT,
  stdio: 'inherit',
  env: { ...process.env, SARANA_BUILD_STANDALONE: '0' },
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
