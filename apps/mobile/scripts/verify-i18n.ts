/**
 * The mobile i18n gate. `pnpm --filter @sarana/mobile verify-i18n`.
 *
 * Two checks, the same two the console runs, for the same reason. On 28 Nov 2025 the DMC
 * press conference for Cyclone Ditwah went out in Sinhala and English only, and
 * Tamil-speaking communities were left without the warning.
 *
 * **1. Every key exists in all three locales.** Delegated to `checkCompleteness` in
 * `@sarana/ts-shared`, so the app, the console and the seed data are held to one
 * definition of complete.
 *
 * **2. Every key the code asks for exists at all.** Completeness compares the catalogues
 * against each other, so a key missing from all three passes - and `t('sync.status.ok')`
 * where the catalogue says `allSynced` then throws `MissingTranslationError` inside the
 * status strip, which is the one component on every screen. Mobile has no namespaces, so
 * this check is stricter than the console's: a `t()` call is a full path or it is dynamic.
 *
 * Dynamic keys are counted, not guessed at. `sync.status.offline.${age.key}` is a real
 * pattern here and pretending to resolve it would either fail honestly-written code or
 * imply a coverage that does not exist. Their prefixes are checked instead: a template
 * literal must at least have a branch in the catalogue.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join, relative } from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { LOCALES, checkCompleteness, formatProblems, type Locale } from '@sarana/ts-shared/i18n';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CATALOGUE = join(ROOT, 'src', 'i18n', 'catalogue');
const SOURCE_DIRS = [join(ROOT, 'src'), join(ROOT, 'app')];

function load(locale: Locale): Record<string, unknown> {
  return JSON.parse(readFileSync(join(CATALOGUE, `${locale}.json`), 'utf8')) as Record<
    string,
    unknown
  >;
}

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return found;
  }
  for (const name of entries) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name === 'node_modules' || name.startsWith('.')) continue;
      found.push(...sourceFiles(path));
    } else if (['.ts', '.tsx'].includes(extname(name)) && !name.endsWith('.test.ts')) {
      found.push(path);
    }
  }
  return found;
}

/** Whether a dotted path resolves to a leaf string. */
function resolves(catalogue: Record<string, unknown>, path: string): boolean {
  let node: unknown = catalogue;
  for (const segment of path.split('.')) {
    if (typeof node !== 'object' || node === null) return false;
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'string';
}

/** Whether a prefix names a branch that exists, for a key built at run time. */
function branchExists(catalogue: Record<string, unknown>, prefix: string): boolean {
  const path = prefix.replace(/\.$/, '');
  if (path.length === 0) return false;
  let node: unknown = catalogue;
  for (const segment of path.split('.')) {
    if (typeof node !== 'object' || node === null) return false;
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'object' && node !== null;
}

const STATIC_CALL = /\bt\(\s*'([A-Za-z0-9_.]+)'/g;
const DYNAMIC_CALL = /\bt\(\s*`([A-Za-z0-9_.]*)\$\{/g;
/** `messageKey: 'sync.status.attention'` and the like, which never reach a `t(` regex. */
const MESSAGE_KEY = /\b(?:messageKey|labelKey|titleKey|bodyKey)\s*:\s*'([A-Za-z0-9_.]+)'/g;

function main(): number {
  const catalogues = Object.fromEntries(
    LOCALES.map((locale) => [locale, load(locale)]),
  ) as Record<Locale, Record<string, unknown>>;

  let failed = false;

  const completeness = checkCompleteness(catalogues);
  if (!completeness.complete) {
    failed = true;
    process.stderr.write(`catalogue: ${completeness.problems.length} problem(s)\n`);
    for (const line of formatProblems(completeness.problems)) {
      process.stderr.write(`${line}\n`);
    }
  }

  const english = catalogues.en;
  const files = SOURCE_DIRS.flatMap((dir) => sourceFiles(dir));
  let checkedKeys = 0;
  let dynamicKeys = 0;

  for (const file of files) {
    const source = readFileSync(file, 'utf8');
    const label = relative(ROOT, file).replaceAll('\\', '/');

    for (const pattern of [STATIC_CALL, MESSAGE_KEY]) {
      for (const match of source.matchAll(pattern)) {
        const key = match[1] ?? '';
        // A single segment is not a catalogue path - it is a local variable or a call to
        // something else entirely. Only dotted keys are ours.
        if (!key.includes('.')) continue;
        checkedKeys += 1;
        if (!resolves(english, key)) {
          failed = true;
          process.stderr.write(`${label}: '${key}' is not in the catalogue\n`);
        }
      }
    }

    for (const match of source.matchAll(DYNAMIC_CALL)) {
      const prefix = match[1] ?? '';
      dynamicKeys += 1;
      if (prefix.includes('.') && !branchExists(english, prefix)) {
        failed = true;
        process.stderr.write(`${label}: '${prefix}*' names no branch in the catalogue\n`);
      }
    }
  }

  if (failed) {
    process.stderr.write(
      '\nNo citizen-facing string exists in fewer than three languages, and no screen ' +
        'renders a key it cannot resolve. Fix the catalogue, not the check.\n',
    );
    return 1;
  }

  process.stdout.write(
    `i18n check passed: ${completeness.keyCount} keys x ${LOCALES.length} locales, ` +
      `${checkedKeys} static usages verified, ${dynamicKeys} dynamic (prefix checked).\n`,
  );
  return 0;
}

process.exit(main());
