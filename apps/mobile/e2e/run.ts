/**
 * `pnpm --filter @sarana/mobile test:e2e -- --config offline.config.ts`
 * `pnpm --filter @sarana/mobile test:e2e -- --assert-sos-duration 30000`
 *
 * Drives Maestro over the flows in `offline.config.ts`. Every one of them needs three
 * things this runner does not provide and cannot fake: an Android emulator or device, a
 * `maestro` binary on the PATH, and an installed build of the app.
 *
 * **When those are missing it exits non-zero and says which one.** It does not skip, and
 * it does not pass. A suite that reports success on a machine with no device is worse
 * than no suite: it turns "the offline path is tested" into a sentence nobody has
 * checked, which is exactly the claim these flows exist to make true.
 */

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import process from 'node:process';
import { fileURLToPath, pathToFileURL } from 'node:url';

import type { OfflineE2EConfig } from './offline.config.js';

const HERE = dirname(fileURLToPath(import.meta.url));

/**
 * Each language's name in its own script, which is the tap target on the picker.
 *
 * Never translated - "Sinhala" in English is no use to someone who cannot read English,
 * which is the whole population the picker exists for. Copied from
 * `@sarana/ts-shared`'s LOCALE_NAMES rather than imported, because Maestro reads these
 * as plain environment strings.
 */
const LOCALE_NAMES: Record<string, string> = {
  si: 'සිංහල',
  ta: 'தமிழ்',
  en: 'English',
};

function argValue(name: string): string | null {
  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1]!;
  const inline = process.argv.find((entry) => entry.startsWith(`--${name}=`));
  return inline ? inline.slice(name.length + 3) : null;
}

function has(command: string): boolean {
  const probe = spawnSync(command, ['--version'], { stdio: 'ignore', shell: true });
  return probe.status === 0;
}

/** Every device `adb` can see, minus the header line. */
function attachedDevices(): string[] {
  const result = spawnSync('adb', ['devices'], { encoding: 'utf8', shell: true });
  if (result.status !== 0) return [];
  return result.stdout
    .split('\n')
    .slice(1)
    .map((line) => line.trim())
    .filter((line) => line.endsWith('device'))
    .map((line) => line.split(/\s+/)[0]!);
}

/**
 * The elapsed milliseconds between the two markers in a flow's JUnit output.
 *
 * Maestro records one `<testcase>` per command with a `time` attribute in seconds. The
 * budget is measured over the commands between `MARKER: sos-start` and `MARKER: sos-end`,
 * which is what a person actually experiences - not the whole flow, which includes signing
 * in and a cold start the emergency path does not pay for.
 *
 * Returns null when the markers are absent, and the caller says so rather than passing.
 */
function markedDurationMs(reportPath: string): number | null {
  if (!existsSync(reportPath)) return null;
  const report = readFileSync(reportPath, 'utf8');

  const start = report.indexOf('sos-start');
  const end = report.indexOf('sos-end');
  if (start < 0 || end < 0 || end < start) return null;

  const between = report.slice(start, end);
  let total = 0;
  for (const match of between.matchAll(/time="([0-9.]+)"/g)) {
    total += Number(match[1] ?? '0');
  }
  return Math.round(total * 1000);
}

async function main(): Promise<number> {
  const configPath = argValue('config') ?? 'offline.config.ts';
  const budgetMs = argValue('assert-sos-duration');
  const resolved = resolve(HERE, configPath);
  if (!existsSync(resolved)) {
    process.stderr.write(`no such config: ${configPath}\n`);
    return 2;
  }

  // pathToFileURL: on Windows an absolute path starts "C:", which the ESM loader reads
  // as a URL scheme and refuses.
  const config = ((await import(pathToFileURL(resolved).href)) as { default: OfflineE2EConfig })
    .default;

  const missing: string[] = [];
  if (!has('maestro')) {
    missing.push(
      'maestro is not on the PATH. Install it with:\n' +
        '    curl -Ls https://get.maestro.mobile.dev | bash',
    );
  }
  if (!has('adb')) {
    missing.push('adb is not on the PATH. Install the Android platform tools.');
  } else if (attachedDevices().length === 0) {
    missing.push(
      `no device or emulator is attached. Start an API ${config.device.apiLevel} ` +
        'emulator, or plug in a handset with USB debugging on.',
    );
  }

  if (missing.length > 0) {
    process.stderr.write(
      `The offline e2e suite covers ${config.flows.length} flows and ran none of them.\n\n`,
    );
    for (const line of missing) process.stderr.write(`  - ${line}\n`);
    process.stderr.write(
      '\nThese flows assert what happens to a day of fieldwork when the network goes ' +
        'away. Reporting them as passed on a machine with no device would make that ' +
        'claim untrue, so this exits non-zero instead.\n\nFlows that did not run:\n',
    );
    for (const flow of config.flows) {
      process.stderr.write(`  ${flow.file}\n    ${flow.title}\n    proves: ${flow.proves}\n`);
    }
    return 1;
  }

  let failed = 0;
  for (const flow of config.flows) {
    for (const locale of flow.locales) {
      process.stdout.write(`\n▸ ${flow.file} [${locale}]\n  ${flow.title}\n`);
      const result = spawnSync(
        'maestro',
        [
          'test',
          join(HERE, 'flows', flow.file),
          '--env',
          `LOCALE=${locale}`,
          '--env',
          `LOCALE_NAME=${LOCALE_NAMES[locale] ?? locale}`,
          '--env',
          `FONT_SCALE=${flow.fontScale ?? 1}`,
          '--format',
          'junit',
          '--output',
          join(HERE, 'results', `${flow.file}.${locale}.xml`),
        ],
        { stdio: 'inherit', shell: true },
      );
      if (result.status !== 0) {
        failed += 1;
        process.stderr.write(`  FAILED - ${flow.proves}\n`);
        continue;
      }

      if (budgetMs !== null) {
        const elapsed = markedDurationMs(join(HERE, 'results', `${flow.file}.${locale}.xml`));
        if (elapsed === null) {
          // Only flows carrying the markers are measured. One that does not is not a
          // failure - but a flow named for the SOS path that carries none is, because it
          // would otherwise pass a budget nothing was measured against.
          if (flow.file.includes('sos')) {
            failed += 1;
            process.stderr.write(
              `  FAILED - ${flow.file} was asked for a duration and carries no ` +
                'sos-start / sos-end markers, so nothing was measured.\n',
            );
          }
          continue;
        }
        const budget = Number(budgetMs);
        process.stdout.write(`  emergency path: ${elapsed}ms against a ${budget}ms budget\n`);
        if (elapsed > budget) {
          failed += 1;
          process.stderr.write(
            `  FAILED - the emergency path took ${elapsed}ms. Past ${budget}ms a person ` +
              'standing in water puts the phone down, and the report is not filed.\n',
          );
        }
      }
    }
  }

  const total = config.flows.reduce((sum, flow) => sum + flow.locales.length, 0);
  process.stdout.write(`\n${total - failed}/${total} flows passed\n`);
  return failed === 0 ? 0 : 1;
}

// `main().then` rather than a top-level await: tsx transpiles this file to CJS, where a
// top-level await is a build error rather than a runtime one.
void main().then((code) => process.exit(code));
