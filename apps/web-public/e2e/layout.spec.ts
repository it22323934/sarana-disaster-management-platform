/**
 * Every route, in all three scripts, checked for overflow at phone width.
 *
 * The brief: "every page renders in si, ta, and en without overflow". The reasoning for
 * measuring overflow rather than comparing pixels is set out at length in
 * `apps/web-ops/e2e/layout.spec.ts`, and the same probe is used here so both apps fail on
 * the same definition.
 *
 * **One thing differs, and it is the important one: the viewport.** The console's gate runs
 * at 1440x900, the resolution an operations room has. This site is read on a cheap phone,
 * so it runs at 390px — where a Sinhala or Tamil heading that is 1.5x its English width has
 * somewhere to break and a seven-column table does not. A gate at desktop width would pass
 * on every page here and prove nothing about the reader the brief names.
 *
 * Two assertions per route per locale:
 *
 *   1. The document does not scroll horizontally. On a touch device a page that does makes
 *      vertical scrolling unreliable, which on a page of tables is most of the interaction.
 *   2. No element clips its own content. `ScrollableTable` wraps every table in an
 *      `overflow-x: auto` box precisely so the tables can be wider than the screen without
 *      tripping this — a table that scrolls inside its own box is the intended design, and
 *      the probe excludes anything inside a deliberately scrollable ancestor.
 */

import { expect, test, type Page } from '@playwright/test';

import { LOCALES } from '@sarana/ts-shared/i18n';

import { ROUTES, SAMPLE_DISTRICT_CODE } from '../src/i18n/routes';

const PATHS = [
  ...ROUTES.map((route) => (route === '/' ? '' : route)),
  `/districts/${SAMPLE_DISTRICT_CODE}`,
];

interface LayoutReport {
  readonly documentOverflowPx: number;
  readonly clipped: ReadonlyArray<{ selector: string; overflowPx: number; text: string }>;
}

/**
 * Measure overflow in the page.
 *
 * Runs in the browser because that is the only place the real font metrics exist, which is
 * the whole reason this suite is worth having alongside the design system's width model.
 * Lifted from the console's gate deliberately: two apps disagreeing about what counts as
 * an overflow would be two gates, and one of them would be the lenient one.
 */
async function measureLayout(page: Page): Promise<LayoutReport> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const clipped: Array<{ selector: string; overflowPx: number; text: string }> = [];

    const describe = (el: Element): string => {
      const id = el.id ? `#${el.id}` : '';
      const cls =
        typeof el.className === 'string' && el.className
          ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}`
          : '';
      return `${el.tagName.toLowerCase()}${id}${cls}`;
    };

    // `sr-only` is one pixel by construction, so its content overflows by design. Measuring
    // the box rather than the clip property catches every spelling of the pattern.
    const visuallyHidden = (el: Element): boolean => el.clientWidth <= 1 || el.clientHeight <= 1;

    const insideScrollable = (el: Element): boolean => {
      for (let node: Element | null = el; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.overflowX === 'auto' || style.overflowX === 'scroll') return true;
      }
      return false;
    };

    for (const el of Array.from(document.querySelectorAll('*'))) {
      const style = getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (style.overflowX !== 'hidden' && style.overflowX !== 'clip') continue;
      if (visuallyHidden(el)) continue;
      if (insideScrollable(el)) continue;

      // A pixel of slack: sub-pixel rounding is not an overflow bug, and an exact equality
      // would fail on font-hinting differences between machines.
      const overflowPx = el.scrollWidth - el.clientWidth;
      if (overflowPx <= 1) continue;

      const text = (el.textContent ?? '').trim();
      if (text.length === 0) continue;

      clipped.push({ selector: describe(el), overflowPx, text: text.slice(0, 60) });
    }

    return { documentOverflowPx: root.scrollWidth - root.clientWidth, clipped };
  });
}

// English last, so a failure names the interesting script first.
for (const locale of ['si', 'ta', 'en'] as const) {
  for (const path of PATHS) {
    const url = `/${locale}${path}`;
    test(`${url} fits at 390px`, async ({ page }) => {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      const report = await measureLayout(page);

      expect(
        report.documentOverflowPx,
        `${url} scrolls horizontally by ${report.documentOverflowPx}px. On a touch device ` +
          'that makes vertical scrolling unreliable.',
      ).toBeLessThanOrEqual(1);

      expect(
        report.clipped,
        `${url} clips content:\n` +
          report.clipped
            .map((entry) => `    ${entry.selector} by ${entry.overflowPx}px: "${entry.text}"`)
            .join('\n'),
      ).toEqual([]);
    });
  }
}

/**
 * The detector, checked against a deliberate overflow.
 *
 * A gate that has only ever passed is indistinguishable from a gate that cannot fail. This
 * injects an element that must be caught, and asserts it is — so a refactor that broke the
 * probe's selector logic fails here rather than turning every route green.
 */
test('the overflow probe catches a clipped element', async ({ page }) => {
  await page.goto('/en', { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    const probe = document.createElement('div');
    probe.id = 'sarana-overflow-probe';
    probe.style.cssText = 'width:80px;overflow-x:hidden;white-space:nowrap;font-size:16px';
    probe.textContent = 'a deliberately long string that cannot possibly fit in eighty pixels';
    document.body.append(probe);
  });

  const report = await measureLayout(page);
  expect(report.clipped.map((entry) => entry.selector)).toContain('div#sarana-overflow-probe');

  await page.evaluate(() => document.getElementById('sarana-overflow-probe')?.remove());
});

/**
 * The three scripts render in their own faces, which is what the type scale is tuned for.
 *
 * Not an overflow check. It asserts the `lang` attribute is right, because that attribute
 * is what selects the Noto face through `tokens.css` and what tells a screen reader which
 * voice to use — and a wrong one produces a page that looks fine and is read aloud as
 * gibberish, which no width measurement would catch.
 */
for (const [locale, tag] of [
  ['si', 'si-LK'],
  ['ta', 'ta-LK'],
  ['en', 'en-LK'],
] as const) {
  test(`/${locale} declares lang="${tag}"`, async ({ page }) => {
    await page.goto(`/${locale}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('html')).toHaveAttribute('lang', tag);
  });
}

test('every locale in LOCALES has a route list entry', () => {
  // Cheap, and it is the guard that stops this suite silently shrinking: the loops above
  // are written against a literal locale tuple for ordering, and this asserts that tuple
  // still covers what the platform supports.
  expect([...LOCALES].sort()).toEqual(['en', 'si', 'ta']);
});
