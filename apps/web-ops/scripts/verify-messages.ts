/**
 * The console's i18n gate. `pnpm --filter @sarana/web-ops verify-i18n`.
 *
 * CI fails on a missing key in any locale. This is not a tidiness rule: on 28 Nov 2025
 * the DMC press conference for Cyclone Ditwah went out in Sinhala and English only, and
 * Tamil-speaking communities were left without the warning. A missing key here is the
 * same failure with a smaller blast radius.
 *
 * It reuses `checkCompleteness` from `@sarana/ts-shared` rather than reimplementing the
 * comparison, so the console, the dashboard and the seed data are all held to one
 * definition of "complete".
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { LOCALES, checkCompleteness, formatProblems } from '@sarana/ts-shared/i18n';

const MESSAGES = join(dirname(fileURLToPath(import.meta.url)), '..', 'messages');

function load(locale: string): unknown {
  return JSON.parse(readFileSync(join(MESSAGES, `${locale}.json`), 'utf8'));
}

function main(): void {
  const catalogues = Object.fromEntries(LOCALES.map((locale) => [locale, load(locale)]));
  const result = checkCompleteness(catalogues as Parameters<typeof checkCompleteness>[0]);

  if (!result.complete) {
    console.error(
      `apps/web-ops/messages: ${result.problems.length} problem(s) across ${result.keyCount} keys\n`,
    );
    for (const line of formatProblems(result.problems)) console.error(line);
    process.exitCode = 1;
    return;
  }

  console.log(`apps/web-ops/messages: ${result.keyCount} keys complete in si, ta and en.`);
}

main();
