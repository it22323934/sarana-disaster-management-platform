/**
 * Every component in the library has a story.
 *
 * This is the test that closes the hole in the axe sweep. The sweep discovers stories and
 * checks them, so a component with no story is a component it never sees - and the
 * failure is invisible, because the sweep still passes. This asserts the other direction:
 * every component the package exports appears in the story catalogue by name.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import * as library from '../index.js';

const HERE = dirname(fileURLToPath(import.meta.url));

/**
 * Exports that are not components, or are components a story cannot mount on its own.
 *
 * Each needs a reason. A growing list here is the same erosion as a growing exemption
 * list in the contrast gate.
 */
const NOT_STORIED: Record<string, string> = {
  // Radix roots, triggers and portal targets. Each renders its children or nothing at
  // all, so a story of one on its own is a story of an empty div. They are all mounted
  // inside the assembly stories, which is where their behaviour actually is.
  SheetRoot: 'a Radix root; Sheet shares its content component and markup with Dialog',
  SheetTrigger: 'a Radix trigger; the Dialog stories cover the identical trigger path',
  SheetClose: 'a Radix close button; identical to the Dialog close it shares code with',
  SheetContent: 'the same primitive and markup as DialogContent, with different geometry',
  PopoverRoot: 'a Radix root that renders only its children',
  PopoverTrigger: 'a Radix trigger; the Select story covers the same trigger path',
  PopoverAnchor: 'a positioning marker that renders no DOM of its own',
  PopoverContent: 'renders only while open; the Select story exercises the same popper',
  DialogClose: 'a Radix close button, mounted inside the DialogAndTooltip story',
  Field: 'the label and error scaffolding, exercised through every Input and Select story',
  SeverityShapeMark: 'the silhouette alone; it is aria-hidden and never rendered by itself',
  // Needs a WebGL context and a live tile server, neither of which exists in jsdom or in
  // a Storybook build. Its layer builders are pure functions and are unit-tested.
  MapShell: 'needs a WebGL context and a tile server; its fallback path is unit-tested',
  // A compatibility alias kept so the pre-design-system scaffold pages keep compiling.
  SimulatedDataBadge: 'an alias of MockDataBadge, which is storied in Domain > Trust',
};

function storySources(): string {
  return readdirSync(HERE)
    .filter((file) => file.endsWith('.stories.tsx'))
    .map((file) => readFileSync(join(HERE, file), 'utf8'))
    .join('\n');
}

/**
 * Exported values that are React components: PascalCase functions that are not classes.
 *
 * `InvalidHexError` is PascalCase and callable, so a naive filter counts it as a
 * component and then demands a story for an Error subclass.
 */
function exportedComponents(): string[] {
  return Object.entries(library)
    .filter(([name, value]) => {
      if (typeof value !== 'function' || !/^[A-Z]/.test(name)) return false;
      // A class's source starts with `class`; a function component's does not.
      return !Function.prototype.toString.call(value).startsWith('class');
    })
    .map(([name]) => name)
    .sort();
}

describe('story coverage', () => {
  const sources = storySources();
  const components = exportedComponents();

  it('exports a plausible number of components', () => {
    // Guards against the barrel breaking and this whole suite passing vacuously.
    expect(components.length).toBeGreaterThan(25);
  });

  it('has a story for every exported component', () => {
    const missing = components.filter(
      (name) => !(name in NOT_STORIED) && !sources.includes(`<${name}`),
    );
    expect(missing).toEqual([]);
  });

  it('gives every exclusion a reason', () => {
    for (const [name, reason] of Object.entries(NOT_STORIED)) {
      expect(reason.length, `${name} needs a real reason`).toBeGreaterThan(20);
    }
  });

  it('does not exclude anything that is in fact storied', () => {
    // A stale exclusion hides the next component that genuinely has no story.
    const staleExclusions = Object.keys(NOT_STORIED).filter((name) =>
      sources.includes(`<${name}`),
    );
    expect(staleExclusions).toEqual([]);
  });
});
