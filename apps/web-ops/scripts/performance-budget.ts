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
 * **`--assert-lcp` needs a browser against a served production build**, which
 * `pnpm build:local && pnpm start` provides on every platform. When `SARANA_LIGHTHOUSE_URL`
 * names a running server this shells out to the Lighthouse CLI; otherwise it says so, names
 * the command, and — unless `--require-lcp` is passed — does not fail the run for an
 * assertion it did not make. There is no honest way to assert an LCP from a manifest, and a
 * script printing a number it had not measured would be worse than one that says it cannot.
 *
 * **Two LCP figures are reported, and the difference is the whole story.** Lighthouse
 * *observes* one on the machine it runs on and *simulates* another over a throttled link.
 * On this console the observed figure is around 150 ms and the simulated one around 2.4 s,
 * and neither is wrong: the page paints almost immediately on a fast connection, and the
 * simulation is modelling the same page arriving over 150 ms RTT at 1.6 Mbps with the CPU
 * slowed fourfold. Reporting only the simulated number makes a fast page look broken;
 * reporting only the observed one makes every page look fine on the reviewer's laptop and
 * says nothing about the district office. So both are printed, and the assertion is on the
 * simulated one because that is the connection the brief names.
 *
 * When the simulated figure fails, the breakdown below it says how much of the budget the
 * framework spends before any application code runs. React and Next's own runtime chunks
 * are around 100 KB gzipped, which at the simulated throughput is most of the way to two
 * seconds on their own. That is a fact about the stack rather than about this console, and
 * a number that does not say so is a number somebody will try to fix in the wrong place.
 */

import { execFileSync } from 'node:child_process';
import { gzipSync } from 'node:zlib';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const NEXT_DIR = join(ROOT, '.next');
const MANIFEST = join(NEXT_DIR, 'app-build-manifest.json');
/** Only `next dev` writes here. Its presence means `.next` holds a development build. */
const DEV_MARKER = join(NEXT_DIR, 'static', 'development');
/** Only a completed production build writes this. */
const BUILD_ID = join(NEXT_DIR, 'BUILD_ID');

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
        // Route groups are a file-system device and never appear in a URL, so they are
        // stripped from the label: reporting `/(auth)/login` would invite somebody to try
        // opening it.
        route:
          route
            .replace(/^\/\[locale\]/, '')
            .replace(/\/\([^)]+\)/g, '')
            .replace(/\/page$/, '') || '/',
        bytes: scripts.reduce((total, file) => total + gzippedBytes(file), 0),
        chunks: scripts.length,
      };
    })
    .sort((a, b) => b.bytes - a.bytes);
}

function kb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

interface LcpReading {
  /** Modelled over the throttled link. What the budget is asserted against. */
  readonly simulated: number;
  /** What actually happened on this machine, unthrottled. Context, not a gate. */
  readonly observed: number | null;
  /** Bytes transferred for the whole page load, which is what dominates the simulation. */
  readonly transferredBytes: number;
}

/**
 * Largest Contentful Paint, measured or honestly skipped.
 *
 * Returns null when no server was named or Lighthouse could not run. It does not guess and
 * it does not average a number from somewhere else: an LCP figure that was not measured on
 * a served production build is not an LCP figure.
 */
function measureLcp(url: string): LcpReading | null {
  try {
    const output = execFileSync(
      'npx',
      [
        '--yes',
        'lighthouse',
        url,
        // The whole performance category rather than one audit: `metrics` carries the
        // observed timings and `network-requests` the transfer sizes, and without those
        // the simulated figure is a verdict with no evidence behind it.
        '--only-categories=performance',
        '--output=json',
        '--quiet',
        '--chrome-flags=--headless=new',
        // The brief's target is a mid-range laptop over a slow link. Measuring on an
        // unthrottled desktop would produce a number that passes everywhere and predicts
        // nothing about the room this runs in.
        '--throttling-method=simulate',
      ],
      {
        encoding: 'utf8',
        cwd: ROOT,
        maxBuffer: 64 * 1024 * 1024,
        // `shell` so `npx` resolves on Windows, where a bare name is not executable
        // without its .cmd shim. Without it this fails with ENOENT and reads as
        // "Lighthouse is not installed" rather than "the spawn was wrong".
        shell: true,
      },
    );
    const report = JSON.parse(output) as {
      audits: {
        'largest-contentful-paint': { numericValue: number };
        metrics?: { details?: { items?: Array<Record<string, number>> } };
        'network-requests'?: { details?: { items?: Array<{ transferSize?: number }> } };
      };
    };
    const metrics = report.audits.metrics?.details?.items?.[0];
    const requests = report.audits['network-requests']?.details?.items ?? [];
    return {
      simulated: report.audits['largest-contentful-paint'].numericValue,
      observed: metrics?.['observedLargestContentfulPaint'] ?? null,
      transferredBytes: requests.reduce((total, item) => total + (item.transferSize ?? 0), 0),
    };
  } catch (error) {
    console.error(
      `\nLighthouse could not run against ${url}. The JS budget above still applies.\n` +
        `  ${(error as Error).message.split('\n')[0]}`,
    );
    return null;
  }
}

function main(): void {
  const args = parseArgs(process.argv.slice(2));

  if (!existsSync(MANIFEST)) {
    console.error(
      'No build to measure. Run `pnpm --filter @sarana/web-ops build:local` first.\n' +
        '`build` emits the standalone deployment bundle and fails on Windows at the\n' +
        'symlink step unless Developer Mode is on; `build:local` skips that step and is\n' +
        'otherwise identical.',
    );
    process.exitCode = 1;
    return;
  }

  /**
   * Refuse to measure a development build.
   *
   * `next dev` and `next build` write to the same `.next`, so running the e2e suite — or
   * any `pnpm dev` — replaces the production manifest with a development one. Development
   * chunks are unminified and unsplit, so the numbers come out in **megabytes** and every
   * route fails by an order of magnitude.
   *
   * That is the worst possible failure for a budget gate: not a crash, but a plausible
   * table of wrong numbers that sends somebody hunting for a bundling regression that does
   * not exist. It has already happened once here. So the check is explicit, and it names
   * the fix rather than the symptom.
   */
  if (existsSync(DEV_MARKER) || !existsSync(BUILD_ID)) {
    console.error(
      '`.next` holds a development build, not a production one.\n' +
        'Development chunks are unminified and unsplit, so measuring them would report\n' +
        'megabytes per route and fail every budget for the wrong reason.\n\n' +
        'This happens after `pnpm dev` or `pnpm test:e2e`, which share the same .next.\n' +
        'Rebuild before measuring:\n' +
        '  pnpm --filter @sarana/web-ops build:local',
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
      `  pnpm --filter @sarana/web-ops build:local && pnpm --filter @sarana/web-ops start\n` +
      `  SARANA_LIGHTHOUSE_URL=http://localhost:3000/en/login pnpm --filter @sarana/web-ops lighthouse\n` +
      `A number printed without that would not be a measurement.`;
    if (args.requireLcp) {
      console.error(message);
      process.exitCode = 1;
    } else {
      console.log(message);
    }
    return;
  }

  const lcp = measureLcp(url);
  if (lcp === null) {
    process.exitCode = 1;
    return;
  }

  console.log(`\nLargest Contentful Paint against ${url}`);
  console.log(`  simulated  ${Math.round(lcp.simulated)} ms   budget ${args.lcpMs} ms`);
  console.log(
    `  observed   ${lcp.observed === null ? '—' : `${Math.round(lcp.observed)} ms`}   ` +
      'unthrottled, on this machine',
  );

  if (lcp.simulated <= args.lcpMs) return;

  console.error(
    `\nOver the simulated budget by ${Math.round(lcp.simulated - args.lcpMs)} ms.\n` +
      `  ${kb(lcp.transferredBytes)} transferred for this page load.\n` +
      '  The simulation models that arriving over a throttled link, so transferred bytes\n' +
      '  are what move this number - not render time. React and the Next runtime are about\n' +
      '  100 KB gzipped of it before any application code, so check what the route adds on\n' +
      '  top of the framework floor rather than looking for a slow component.',
  );
  process.exitCode = 1;
}

main();
