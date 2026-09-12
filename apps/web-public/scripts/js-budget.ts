/**
 * The JavaScript budget. `pnpm --filter web-public budget`
 *
 * Build file 21: "Under 120KB JS on the initial route." This measures it and fails when it
 * is exceeded, per route, because the budget is per route — the districts page carries the
 * map's entry point and the overview must not.
 *
 * **Gzipped, because that is what crosses the wire.** Next's own build output reports the
 * same figure; this script exists so the number is an assertion rather than something a
 * reader has to notice in a wall of build output.
 *
 * **What it does not measure: the LCP.** The brief also asks for "LCP under 1.5s on 3G",
 * and there is no honest way to assert that from a build manifest. web-ops has the same
 * split and resolves it the same way — see `apps/web-ops/scripts/performance-budget.ts`,
 * which shells out to Lighthouse against a served build and says plainly when it has not
 * measured. Rather than duplicate that machinery here, this script asserts the half it can
 * compute and names the other half rather than passing quietly over it.
 *
 * The measurement that mattered: importing `MockDataBadge` from the `@sarana/ui` root
 * barrel put 69 KB gzipped of Radix into every route of a site with no interactive control
 * on it, and took the overview from 105 KB to 186 KB. `@sarana/ui/server` exists because of
 * this script.
 */

import { gzipSync } from 'node:zlib';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const NEXT_DIR = join(ROOT, '.next');
const MANIFEST = join(NEXT_DIR, 'app-build-manifest.json');
const BUILD_ID = join(NEXT_DIR, 'BUILD_ID');

/** The brief's figure. Overridable so a tighter budget can be trialled, never loosened silently. */
const DEFAULT_BUDGET_KB = 120;

function budgetKb(): number {
  const flag = process.argv.indexOf('--budget-kb');
  if (flag === -1) return DEFAULT_BUDGET_KB;
  const value = Number.parseFloat(process.argv[flag + 1] ?? '');
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_BUDGET_KB;
}

function gzippedBytes(file: string): number {
  const path = join(NEXT_DIR, file);
  return existsSync(path) ? gzipSync(readFileSync(path)).length : 0;
}

function main(): void {
  if (!existsSync(BUILD_ID) || !existsSync(MANIFEST)) {
    console.error(
      'No production build found. Run `pnpm --filter web-public build:local` first.\n' +
        'A development build has different chunking and measuring it would report a ' +
        'number that means nothing.',
    );
    process.exitCode = 1;
    return;
  }

  const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8')) as {
    pages: Record<string, string[]>;
  };

  const budget = budgetKb();
  const rows = Object.entries(manifest.pages)
    // Layouts and route handlers are not routes a reader lands on. A route handler
    // returning JSON ships no script to anybody, and counting it would pad the report
    // with rows that can never fail.
    .filter(([route]) => route.endsWith('/page'))
    .map(([route, files]) => ({
      route,
      kb: files.filter((file) => file.endsWith('.js')).reduce((sum, file) => sum + gzippedBytes(file), 0) / 1024,
    }))
    .sort((a, b) => b.kb - a.kb);

  console.log(`Initial JavaScript per route, gzipped. Budget ${budget} KB.\n`);
  for (const row of rows) {
    const over = row.kb > budget;
    console.log(`  ${over ? 'FAIL' : 'ok  '}  ${row.kb.toFixed(1).padStart(7)} KB  ${row.route}`);
  }

  const failures = rows.filter((row) => row.kb > budget);
  if (failures.length > 0) {
    console.error(
      `\n${failures.length} route(s) over ${budget} KB gzipped.\n` +
        'Before trimming application code, check what was imported: the single largest\n' +
        'win on this app was importing from `@sarana/ui/server` rather than the root\n' +
        'barrel, which removed 69 KB of Radix from every page.',
    );
    process.exitCode = 1;
    return;
  }

  console.log(`\nEvery route is within ${budget} KB gzipped.`);
  console.log(
    '\nNot measured here: LCP under 1.5s on 3G. That needs a browser against a served\n' +
      'production build; see apps/web-ops/scripts/performance-budget.ts for the pattern.',
  );
}

main();
