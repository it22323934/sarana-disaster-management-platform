/**
 * axe over every route, in all three scripts. `pnpm --filter web-public test:a11y`
 *
 * Zero violations on every route, which the brief states without qualification.
 *
 * **Colour contrast is checked here, unlike in the design system's own sweep.** File 19
 * disables `color-contrast` when running axe over the Storybook catalogue, because stories
 * render components on a transparent canvas where axe cannot resolve the effective
 * background and reports a wall of false positives. This suite loads real pages with the
 * real theme mounted, so the check works and is left on — and it is the check that matters
 * most on a page read in daylight on a phone.
 *
 * Run against `next dev` rather than a production build. What axe inspects is the rendered
 * accessibility tree, which the two builds agree about; the difference between them is
 * bundling, which is the JavaScript budget's problem rather than this suite's.
 */

import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

import { LOCALES } from '@sarana/ts-shared/i18n';

import { ROUTES, SAMPLE_DISTRICT_CODE } from '../src/i18n/routes';

const PAGES = LOCALES.flatMap((locale) => [
  ...ROUTES.map((route) => ({
    locale,
    path: route === '/' ? `/${locale}` : `/${locale}${route}`,
  })),
  { locale, path: `/${locale}/districts/${SAMPLE_DISTRICT_CODE}` },
]);

for (const { locale, path } of PAGES) {
  test(`${path} has no axe violations in ${locale}`, async ({ page }) => {
    await page.goto(path, { waitUntil: 'domcontentloaded' });

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      // The map canvas is excluded and nothing else is. MapLibre renders a WebGL canvas
      // whose internals axe cannot inspect; the `role="img"` wrapper with its label *is*
      // checked, and the table carrying the same figures is checked in full. Excluding the
      // canvas is not excluding the content — the content has a server-rendered twin.
      .exclude('.maplibregl-canvas-container')
      .analyze();

    const summary = results.violations
      .map(
        (violation) =>
          `${violation.id} (${violation.impact}): ${violation.help}\n` +
          violation.nodes.map((node) => `    ${node.html.slice(0, 160)}`).join('\n'),
      )
      .join('\n');

    expect(results.violations, `${path} in ${locale}:\n${summary}`).toEqual([]);
  });
}
