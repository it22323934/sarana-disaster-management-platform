/**
 * The console's i18n gate. `pnpm --filter @sarana/web-ops verify-i18n`.
 *
 * Two checks, and the second exists because the first was not enough.
 *
 * **1. Every key exists in every locale.** This is not a tidiness rule: on 28 Nov 2025 the
 * DMC press conference for Cyclone Ditwah went out in Sinhala and English only, and
 * Tamil-speaking communities were left without the warning. A missing key here is the same
 * failure with a smaller blast radius. It reuses `checkCompleteness` from
 * `@sarana/ts-shared` rather than reimplementing the comparison, so the console, the
 * dashboard and the seed data are all held to one definition of "complete".
 *
 * **2. Every key the code asks for exists at all.** Completeness compares the three
 * catalogues against each other, so a key missing from all three passes — and
 * `t('totpHint')` where the catalogue says `totpPrompt` then renders the literal string
 * `auth.totpHint` to every user in every language. That is a worse failure than a missing
 * translation, because it is wrong in the language the author speaks and so is the one
 * they are least likely to notice. It was found by an accessibility sweep rather than by
 * this script, which is the wrong place to find it.
 *
 * The second check is deliberately conservative. It resolves only what it can read
 * statically — `const t = useTranslations('ns')`, then `t('key')` — and counts dynamic
 * keys as skipped rather than guessing. A computed key is a real pattern here
 * (`t(`areaMode_${mode}`)`) and pretending to check it would either produce false failures
 * or, worse, a false sense that everything is covered.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { LOCALES, checkCompleteness, formatProblems } from '@sarana/ts-shared/i18n';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MESSAGES = join(ROOT, 'messages');
const SOURCE_DIRS = [join(ROOT, 'src'), join(ROOT, 'app')];

function load(locale: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(MESSAGES, `${locale}.json`), 'utf8')) as Record<
    string,
    unknown
  >;
}

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      // `.next` holds compiled copies of these same files; scanning them would double
      // every finding and report line numbers nobody can open.
      if (name === 'node_modules' || name.startsWith('.')) continue;
      found.push(...sourceFiles(path));
    } else if (['.ts', '.tsx'].includes(extname(name))) {
      found.push(path);
    }
  }
  return found;
}

/** Whether `ns.key` resolves to a leaf string in the catalogue. */
function resolves(catalogue: Record<string, unknown>, path: string): boolean {
  let node: unknown = catalogue;
  for (const segment of path.split('.')) {
    if (typeof node !== 'object' || node === null) return false;
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === 'string';
}

interface Usage {
  readonly file: string;
  readonly key: string;
}

interface Binding {
  readonly at: number;
  readonly name: string;
  readonly namespace: string;
}

const BINDING = /const\s+(\w+)\s*=\s*useTranslations\(\s*(?:'([^']*)')?\s*\)/g;

/**
 * Every statically resolvable `t('key')` in one file, as full `namespace.key` paths.
 *
 * **Bindings are resolved positionally, not by name alone.** One file routinely holds
 * several components, each with its own `const t = useTranslations(...)` bound to a
 * different namespace — `dispatch` in one and `cop` in the next. Keeping one entry per
 * name would resolve every call against whichever declaration happened to be last, which
 * reports dozens of real keys as missing and buries any genuine finding in the noise. So
 * each binding is recorded with its offset, and a call takes the nearest one above it.
 *
 * A `useTranslations()` with no namespace binds to the root, and calls on it are already
 * full paths.
 */
function usagesIn(file: string): { usages: Usage[]; dynamic: number } {
  const source = readFileSync(file, 'utf8');

  const bindings: Binding[] = [];
  for (const match of source.matchAll(BINDING)) {
    bindings.push({
      at: match.index ?? 0,
      name: match[1] ?? '',
      namespace: match[2] ?? '',
    });
  }
  if (bindings.length === 0) return { usages: [], dynamic: 0 };

  const names = [...new Set(bindings.map((entry) => entry.name))].filter(
    (name) => name.length > 0,
  );
  if (names.length === 0) return { usages: [], dynamic: 0 };

  /** The namespace in scope for `name` at this offset: the nearest binding above it. */
  function namespaceFor(name: string, at: number): string | null {
    let found: string | null = null;
    for (const entry of bindings) {
      if (entry.name !== name || entry.at > at) continue;
      found = entry.namespace;
    }
    return found;
  }

  const usages: Usage[] = [];
  let dynamic = 0;
  const call = new RegExp(String.raw`\b(` + names.join('|') + String.raw`)\(\s*([^)]*?)\s*[,)]`, 'g');

  for (const match of source.matchAll(call)) {
    const name = match[1] ?? '';
    const argument = match[2] ?? '';
    const at = match.index ?? 0;
    const namespace = namespaceFor(name, at);
    // A call above every binding of that name is the declaration itself, or an unrelated
    // function that happens to share the name. Neither is a message lookup.
    if (namespace === null) continue;

    const literal = /^'([^']*)'$/.exec(argument);
    if (!literal) {
      // A template literal or a variable. Counted, never guessed at.
      if (argument.length > 0) dynamic += 1;
      continue;
    }
    usages.push({
      file: file.slice(ROOT.length + 1),
      key: namespace ? `${namespace}.${literal[1]}` : (literal[1] ?? ''),
    });
  }
  return { usages, dynamic };
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

  // English is the reference for the second check. The first has already proved the three
  // are identical in shape, so any one of them would do.
  const reference = catalogues['en'] as Record<string, unknown>;
  const missing: Usage[] = [];
  let checked = 0;
  let dynamic = 0;

  for (const dir of SOURCE_DIRS) {
    for (const file of sourceFiles(dir)) {
      const found = usagesIn(file);
      dynamic += found.dynamic;
      for (const usage of found.usages) {
        checked += 1;
        if (!resolves(reference, usage.key)) missing.push(usage);
      }
    }
  }

  if (missing.length > 0) {
    console.error(
      `apps/web-ops: ${missing.length} message key(s) used in code and absent from the catalogue.\n` +
        'These render as the literal key path to every user, in every language.\n',
    );
    for (const usage of missing) console.error(`  ${usage.file}: ${usage.key}`);
    process.exitCode = 1;
    return;
  }

  console.log(
    `apps/web-ops/messages: ${result.keyCount} keys complete in si, ta and en; ` +
      `${checked} literal key uses resolve (${dynamic} dynamic, not checked).`,
  );
}

main();
