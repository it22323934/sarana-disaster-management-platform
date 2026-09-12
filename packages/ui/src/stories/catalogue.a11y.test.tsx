/**
 * axe over every story in the catalogue. `pnpm --filter @sarana/ui test:a11y`.
 *
 * The catalogue is discovered rather than listed: every named export of every
 * `*.stories.tsx` is rendered and checked. A component added to the library without a
 * story is therefore a component this sweep never sees, which is the one hole in it - and
 * it is why `stories.test.ts` separately asserts that every exported component appears in
 * some story.
 *
 * **What this catches and what it does not.** jsdom has no layout and no cascade, so
 * axe's `color-contrast` rule cannot run here and is disabled explicitly rather than
 * silently skipped. Colour is gated instead by `pnpm test:contrast`, which measures every
 * declared token pairing against WCAG 2.2 - a stronger check than axe would perform,
 * because it covers both surfaces and every state rather than only what happens to be on
 * screen. What this sweep does catch is the structural half: missing accessible names,
 * unlabelled controls, broken ARIA relationships, duplicate ids, list and table
 * semantics, and heading order.
 */

/// <reference types="vite/client" />

import axe, { type Result } from 'axe-core';
import { render } from '@testing-library/react';
import { isValidElement } from 'react';
import { describe, expect, it } from 'vitest';

type StoryModule = Record<string, unknown>;

/**
 * Vite resolves this at build time, so the sweep grows automatically with the catalogue.
 *
 * Typed through a local alias because `tsc --build` compiles this file too and does not
 * know `import.meta.glob`; the triple-slash reference above supplies Vite's types.
 */
const modules: Record<string, StoryModule> = import.meta.glob<StoryModule>(
  './*.stories.tsx',
  { eager: true },
);

/** Story exports that are not stories. */
const NOT_A_STORY = new Set(['default', '__namedExportsOrder']);

interface DiscoveredStory {
  readonly file: string;
  readonly name: string;
  readonly render: () => React.ReactNode;
}

function discover(): DiscoveredStory[] {
  const stories: DiscoveredStory[] = [];
  for (const [file, module] of Object.entries(modules)) {
    for (const [name, value] of Object.entries(module)) {
      if (NOT_A_STORY.has(name)) continue;
      if (typeof value !== 'object' || value === null) continue;
      const candidate = value as { render?: () => React.ReactNode };
      if (typeof candidate.render !== 'function') continue;
      stories.push({ file, name, render: candidate.render });
    }
  }
  return stories;
}

const STORIES = discover();

function describeViolation(violation: Result): string {
  const nodes = violation.nodes
    .slice(0, 3)
    .map((node) => `      ${node.html.slice(0, 120)}`)
    .join('\n');
  return `  ${violation.id} (${violation.impact ?? 'unknown'}): ${violation.help}\n${nodes}`;
}

describe('the story catalogue', () => {
  it('found stories to check', () => {
    // A glob that silently matches nothing would make this whole suite pass by doing
    // nothing at all, which is the failure mode of every discovery-based test.
    expect(STORIES.length).toBeGreaterThan(10);
  });

  it.each(STORIES.map((story) => [`${story.file} > ${story.name}`, story] as const))(
    'has no axe violations: %s',
    async (_label, story) => {
      const element = story.render();
      expect(isValidElement(element)).toBe(true);

      const { container } = render(element);

      const results = await axe.run(container, {
        rules: {
          // Cannot be evaluated without layout and a cascade. Covered by test:contrast.
          'color-contrast': { enabled: false },
          // Stories are fragments mounted into a bare div, not documents; landmark and
          // page-level rules would fail on the harness rather than on the component.
          region: { enabled: false },
          'page-has-heading-one': { enabled: false },
          'landmark-one-main': { enabled: false },
        },
      });

      const violations = results.violations;
      expect(
        violations.length,
        violations.length === 0
          ? ''
          : `${violations.length} axe violation(s):\n${violations.map(describeViolation).join('\n')}`,
      ).toBe(0);
    },
  );
});
