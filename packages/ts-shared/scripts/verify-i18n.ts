/**
 * `pnpm --filter @sarana/ts-shared verify-i18n`
 *
 * Walks every locale catalogue in the workspace and fails if si, ta and en do not carry
 * exactly the same key set with no blank values. CI blocks a merge on this, and so does
 * the pre-commit hook.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import process from 'node:process';

import { checkCompleteness, formatProblems } from '../src/i18n/completeness.js';
import { LOCALES, type Locale } from '../src/i18n/types.js';

const REPO_ROOT = resolve(import.meta.dirname, '../../..');
const SEARCH_ROOTS = ['packages', 'apps', 'services'];
const SKIP = new Set(['node_modules', '.next', '.turbo', 'dist', 'build', '.venv', '.expo']);

/** Every directory holding at least one `{locale}.json`. */
function findCatalogueDirs(root: string, found: Set<string> = new Set()): Set<string> {
  let entries: string[];
  try {
    entries = readdirSync(root);
  } catch {
    return found;
  }

  for (const entry of entries) {
    if (SKIP.has(entry)) continue;
    const path = join(root, entry);
    if (statSync(path).isDirectory()) {
      findCatalogueDirs(path, found);
    } else if (LOCALES.some((locale) => entry === `${locale}.json`)) {
      found.add(root);
    }
  }
  return found;
}

function main(): number {
  const directories = SEARCH_ROOTS.flatMap((name) => [
    ...findCatalogueDirs(join(REPO_ROOT, name)),
  ]).sort();

  let failed = false;
  let checked = 0;

  for (const directory of directories) {
    const catalogues = {} as Record<Locale, unknown>;
    const missingFiles: Locale[] = [];

    for (const locale of LOCALES) {
      try {
        catalogues[locale] = JSON.parse(readFileSync(join(directory, `${locale}.json`), 'utf8'));
      } catch {
        missingFiles.push(locale);
        catalogues[locale] = {};
      }
    }

    const label = relative(REPO_ROOT, directory).replaceAll('\', '/');
    if (missingFiles.length > 0) {
      failed = true;
      process.stderr.write(`${label}: missing ${missingFiles.join(', ')}.json entirely\n`);
      continue;
    }

    const result = checkCompleteness(catalogues);
    checked += 1;
    if (!result.complete) {
      failed = true;
      process.stderr.write(`${label}: ${result.problems.length} problem(s)\n`);
      for (const line of formatProblems(result.problems)) {
        process.stderr.write(`${line}\n`);
      }
    }
  }

  if (failed) {
    process.stderr.write(
      '\nEvery citizen-facing string must exist in si, ta and en. If a translation is ' +
        'not ready, the record does not ship - it goes to the pending_translation queue.\n',
    );
    return 1;
  }

  process.stdout.write(`i18n completeness check passed (${checked} catalogue(s)).\n`);
  return 0;
}

process.exit(main());
