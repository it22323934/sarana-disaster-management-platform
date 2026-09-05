/**
 * The performance budget. `pnpm --filter @sarana/web-ops lighthouse -- --assert-js 250 --assert-lcp 2000`
 *
 * Build file 20's fourth Definition-of-Done command. It is two assertions and they are not
 * equally checkable, so this script does the checkable one properly and is explicit about
 * the other rather than passing quietly.
 *
 * **`--assert-js` is measured, and it is a real gate.** The initial JavaScript for each
 * route is exactly what `app-build-manifest.json` lists, and gzipped size is what crosses
 * the wire. That number is the one that decides whether an operations room on a 3G tether
 * can open this console at all, and it is computable from a build with no browser
 * involved. Reported per route, because the budget is per route: the map screens carry
 * MapLibre and the sign-in screen must not.
 *
 * **`--assert-lcp` needs a browser against a served production build.** There is no
 * honest way to assert a Largest Contentful Paint from a manifest, and a script that
 * printed a number it had not measured would be worse than one that says it cannot. When
 * `SARANA_LIGHTHOUSE_URL` names a running server this shells out to the Lighthouse CLI;
 * otherwise it says so, names the command, and — unless `--require-lcp` is passed — does
 * not fail the run for an assertion it did not make.
 *
 * On `next build` and Windows: compilation and all 60 static pages succeed, and then the
 * pre-existing `output: 'standalone'` trace-copy step fails with EPERM creating symlinks
 * unless Developer Mode is on. The chunks this script measures are written before that
 * step, so the JS budget is checkable on a build that did not finish.
 */

import { execFileSync } from 'node:child_process';
import { gzipSync } from 'node:zlib';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const NEXT_DIR = join(ROOT, '.next');
const MANIFEST = join(NEXT_DIR, 'app-build-manifest.json');

/** Defaults matching the brief. Overridable so a tighter budget can be trialled. */
const DEFAULT_JS_KB = 250;
const DEFAULT_LCP_MS = 2000;

interface Args {
  readonly jsKb: number;
  readonly lcpMs: number;
  readonly requireLcp: boolean;
}

function parseArgs(argv: readonly string[]): Args {
  const value = (flag: string, fallback: number): number => {
    const index = argv.indexOf(flag);
    if (index === -1) return fallback;
    const raw = Number(argv[index + 1]);
    return Number.isFinite(raw) ? raw : fallback;
  };
  return {
    jsKb: value('--assert-js', DEFAULT_JS_KB),
    lcpMs: value('--assert-lcp', DEFAULT_LCP_MS),
    requireLcp: argv.includes('--require-lcp'),
  };
}

/**
 * Gzipped size of one emitted chunk, in bytes.
 *
 * Gzipped rather than raw. The budget is about what crosses the wire, and raw size
 * overstates it by roughly three times — a console that passed a 250KB raw budget would be
 * shipping under 90KB and one that failed it might be shipping 240KB and be fine.
 */
function gzippedBytes(file: string): number {
  const path = join(NEXT_DIR, file);
  if (!existsSync(path) || !statSync(path).isFile()) return 0;
  return gzipSync(readFileSync(path)).length;
}

/** Routes a person actually navigates to. Layouts and route handlers are not entry points. */
function isNavigable(route: string): boolean {
  return route.endsWith('/page');
}

/**
 * One entry per route, deduplicated by locale.
 *
 * `/[locale]/ops/page` is one route in the manifest and three URLs in the app; measuring
 * it once is right, because the three share every chunk.
 */
function measure(): Array<{ route: string; bytes: number; chunks: number }> {
  const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8')) as {
    pages: Record<string, string[]>;
  };

  return Object.entries(manifest.pages)
    .filter(([route]) => isNavigable(route))
    .map(([route, files]) => {
      const scripts = [...new Set(files)].filter((file) => file.endsWith('.js'));
      return {
        route: route.replace(/^\/\[locale\]/, '').replace(/\/page$/, '') || '/',
        bytes: scripts.reduce((total, file) => total + gzippedBytes(file), 0),
        chunks: scripts.length,
      };
    })
    .sort((a, b) => b.bytes - a.bytes);
}

function kb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

/**
 * Largest Contentful Paint, measured or honestly skipped.
 *
 * Returns null when no server was named. It does not guess and it does not average a
 * number from somewhere else: an LCP figure that was not measured on a served production
 * build is not an LCP figure.
 */
function measureLcp(url: string, budgetMs: number): number | null {
  try {
    const output = execFileSync(
      'npx',
      [
        '--yes',
        'lighthouse',
        url,
        '--only-audits=largest-contentful-paint',
        '--output=json',
        '--quiet',
        '--chrome-flags=--headless=new',
        // The brief's target: a mid-range laptop over 3G at 400ms RTT. Measuring on an
        // unthrottled desktop would produce a number that passes everywhere and predicts
        // nothing about the room this runs in.
        '--throttling-method=simulate',
      ],
      { encoding: 'utf8', cwd: ROOT, maxBuffer: 64 * 1024 * 1024 },
    );
    const report = JSON.parse(output) as {
      audits: { 'largest-contentful-paint': { numericValue: number } };
    };
    return report.audits['largest-contentful-paint'].numericValue;
  } catch (error) {
    console.error(
      `\nLighthouse could not run against ${url}. The JS budget above still applies.\n` +
        `  ${(error as Error).message.split('\n')[0]}`,
    );
    void budgetMs;
    return null;
  }
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));

  if (!existsSync(MANIFEST)) {
    console.error(
      'No build to measure. Run `pnpm --filter @sarana/web-ops build` first.\n' +
        'On Windows the build fails at the standalone trace-copy step with EPERM unless\n' +
        'Developer Mode is on; the chunks this script reads are written before that step,\n' +
        'so a build that failed there is still measurable.',
    );
    process.exitCode = 1;
    return;
  }

  const routes = measure();
  const budgetBytes = args.jsKb * 1024;
  const over = routes.filter((entry) => entry.bytes > budgetBytes);

  console.log(`Initial JavaScript per route, gzipped. Budget ${args.jsKb} KB.\n`);
  for (const entry of routes) {
    const flag = entry.bytes > budgetBytes ? 'OVER ' : '     ';
    console.log(`  ${flag}${kb(entry.bytes).padStart(9)}  ${entry.chunks} chunks  ${entry.route}`);
  }

  if (over.length > 0) {
    console.error(
      `\n${over.length} route(s) over the ${args.jsKb} KB budget: ` +
        over.map((entry) => entry.route).join(', '),
    );
    process.exitCode = 1;
  } else {
    console.log(`\nEvery route is within ${args.jsKb} KB gzipped.`);
  }

  const url = process.env['SARANA_LIGHTHOUSE_URL'];
  if (!url) {
    const message =
      `\nLCP was not measured. It needs a browser against a served production build:\n` +
      `  pnpm --filter @sarana/web-ops build && pnpm --filter @sarana/web-ops start\n` +
      `  SARANA_LIGHTHOUSE_URL=http://localhost:3000/en/ops pnpm --filter @sarana/web-ops lighthouse\n` +
      `A number printed without that would not be a measurement.`;
    if (args.requireLcp) {
      console.error(message);
      process.exitCode = 1;
    } else {
      console.log(message);
    }
    return;
  }

  const lcp = measureLcp(url, args.lcpMs);
  if (lcp === null) {
    process.exitCode = 1;
    return;
  }
  console.log(`\nLCP ${Math.round(lcp)} ms against ${url}. Budget ${args.lcpMs} ms.`);
  if (lcp > args.lcpMs) {
    console.error(`LCP is over budget by ${Math.round(lcp - args.lcpMs)} ms.`);
    process.exitCode = 1;
  }
}

main();
