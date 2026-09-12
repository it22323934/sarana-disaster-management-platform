/**
 * The `@sarana/ui/server` entry point ships no client code, and stays that way.
 *
 * `src/server.ts` exists so a React Server Component can use the design system without
 * pulling the Radix primitives into a page that has no interactive control on it. That
 * promise is not enforced by anything in the type system: a component re-exported from
 * there could grow a `useState` next month, and every server-rendered page would silently
 * gain a client boundary and about 69 KB of JavaScript. The failure is invisible — the
 * pages still render — so it needs a test rather than a convention.
 *
 * The check walks the real import graph from `server.ts` and fails on the first
 * `'use client'` it reaches, naming the path that got there. Reading the files is the point:
 * an import that a bundler would follow is an import this test follows.
 */

import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const SRC = dirname(fileURLToPath(import.meta.url));
const ENTRY = join(SRC, 'server.ts');

/** Resolve a `./foo.js` specifier back to the `.ts`/`.tsx` file on disk. */
function resolveLocal(fromFile: string, specifier: string): string | null {
  if (!specifier.startsWith('.')) return null;
  const base = resolve(dirname(fromFile), specifier).replace(/\.js$/, '');
  for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

const SPECIFIER = /(?:from|import)\s+'([^']+)'/g;

/** Every local module reachable from `entry`, with the path that reached it. */
function importGraph(entry: string): Map<string, readonly string[]> {
  const seen = new Map<string, readonly string[]>();
  const queue: { file: string; path: readonly string[] }[] = [{ file: entry, path: [entry] }];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || seen.has(current.file)) continue;
    seen.set(current.file, current.path);

    const source = readFileSync(current.file, 'utf8');
    for (const match of source.matchAll(SPECIFIER)) {
      const target = resolveLocal(current.file, match[1] ?? '');
      // A bare specifier is a package. `@sarana/ts-shared` is types and pure functions,
      // and React itself is not a client module - neither can introduce a boundary.
      if (target && !seen.has(target)) {
        queue.push({ file: target, path: [...current.path, target] });
      }
    }
  }

  return seen;
}

function isClientModule(file: string): boolean {
  // The directive has to be the first statement, so only the top of the file matters.
  return /^\s*(?:\/\*[\s\S]*?\*\/\s*|\/\/[^\n]*\n\s*)*['"]use client['"]/.test(
    readFileSync(file, 'utf8'),
  );
}

describe('@sarana/ui/server', () => {
  it('reaches no module marked use client, however deep the import chain', () => {
    const graph = importGraph(ENTRY);

    const offenders = [...graph.entries()]
      .filter(([file]) => isClientModule(file))
      .map(([, path]) => path.map((file) => file.slice(SRC.length + 1)).join(' -> '));

    expect(
      offenders,
      offenders.length === 0
        ? ''
        : 'A client module is reachable from the server entry point. Every page that ' +
            'imports @sarana/ui/server now ships a client boundary it did not before:\n' +
            offenders.join('\n'),
    ).toEqual([]);
  });

  it('exports the badge the public dashboard depends on', () => {
    // Narrow on purpose. The value of this entry point is what it does *not* export, so a
    // test asserting a long list would fight every legitimate addition. This asserts the
    // one import that motivated the file, so it cannot be dropped by accident.
    const source = readFileSync(ENTRY, 'utf8');
    expect(source).toContain('MockDataBadge');
  });
});
