/**
 * The PII sweep. `pnpm --filter web-public test:pii-sweep`
 *
 * The most important test on this app, and the reason is worth stating plainly: the privacy
 * claim is enforced in three places that do not depend on each other, and this is the only
 * one that looks at what was actually published.
 *
 * 1. The SQL selects nothing identifying. A column that is never in the row cannot leak.
 * 2. The response models carry no field for it.
 * 3. This sweep reads the bytes and looks anyway.
 *
 * The third exists because the first two are promises about intent. A page that
 * interpolated a division code into a caption, or an export that grew a column "for
 * debugging", would satisfy both and still publish something it should not.
 *
 * **Every route, every locale, and every export.** Thirty-three page fetches plus the JSON
 * feed, the CSV and the GeoJSON. A sweep over a sample would be a sweep that passes until
 * the day somebody adds the wrong thing to the page it skipped.
 *
 * The HTML is swept twice, in two ways, because a leak can hide in either half: once over
 * the visible text, and once over the RSC flight payload inside `<script>` — which is where
 * a prop passed to a client component ends up, and which `visibleText` deliberately strips
 * so the two failures are reported separately rather than doubled.
 */

import { expect, test } from '@playwright/test';

import { LOCALES } from '@sarana/ts-shared/i18n';

import { ROUTES, SAMPLE_DISTRICT_CODE } from '../src/i18n/routes';
import { describeFindings, findPii, findPiiInJson, visibleText } from '../src/lib/pii';

/** Every page a reader can reach, in every language. */
const PAGES = LOCALES.flatMap((locale) => [
  ...ROUTES.map((route) => (route === '/' ? `/${locale}` : `/${locale}${route}`)),
  `/${locale}/districts/${SAMPLE_DISTRICT_CODE}`,
]);

test.describe('no public surface publishes personal data', () => {
  for (const path of PAGES) {
    test(`${path} contains nothing that matches the PII battery`, async ({ page }) => {
      const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
      expect(response?.status(), `${path} did not render`).toBeLessThan(400);

      const html = await page.content();

      const inText = findPii(visibleText(html));
      expect(inText, describeFindings(`the visible text of ${path}`, inText)).toEqual([]);

      // The flight payload: everything React serialised for the client. A page with no
      // client components has almost nothing here, and that is itself worth asserting -
      // if a prop starts carrying a household id it lands in exactly this string.
      const scripts = html.match(/<script[^>]*>([\s\S]*?)<\/script>/g) ?? [];
      const inScripts = findPii(scripts.join(' '));
      expect(inScripts, describeFindings(`the script payload of ${path}`, inScripts)).toEqual(
        [],
      );
    });
  }

  test('the JSON ledger feed contains nothing that matches the battery', async ({ request }) => {
    const response = await request.get('/api/public/ledger?limit=200');
    expect(response.status()).toBe(200);

    const body = (await response.json()) as unknown;
    const findings = findPiiInJson(body);
    expect(findings, describeFindings('the JSON ledger feed', findings)).toEqual([]);
  });

  test('the CSV export contains nothing that matches the battery', async ({ request }) => {
    const response = await request.get('/api/public/ledger?limit=200&format=csv');
    expect(response.status()).toBe(200);

    const csv = await response.text();
    const findings = findPii(csv);
    expect(findings, describeFindings('the CSV export', findings)).toEqual([]);
  });

  test('the district GeoJSON carries boundaries and no household position', async ({
    request,
  }) => {
    const response = await request.get('/api/public/districts.geojson');
    expect(response.status()).toBe(200);

    const body = (await response.json()) as { features: unknown[] };

    // Coordinates are the point of this payload, so the coordinate pattern would fire on
    // every vertex. What is asserted instead is the property that matters: a feature
    // carries a district code and nothing else. A household position would arrive as an
    // extra property, and this catches that without pretending a polygon is a leak.
    for (const feature of body.features as {
      properties: Record<string, unknown>;
    }[]) {
      expect(Object.keys(feature.properties).sort()).toEqual(['district_code']);
    }

    const findings = findPiiInJson(body.features.map((f) => (f as { properties: unknown }).properties));
    expect(findings, describeFindings('the GeoJSON properties', findings)).toEqual([]);
  });
});

test.describe('the sweep is not vacuous', () => {
  /**
   * A guard against the failure mode that makes every sweep worthless: passing because it
   * looks at nothing.
   *
   * If a route stopped rendering, or the fetchers silently returned empty, every assertion
   * above would pass over an empty page. This asserts the pages the sweep reads are the
   * pages a reader sees, by checking one figure the fixtures put on them.
   */
  test('the swept pages actually contain the figures they publish', async ({ page }) => {
    await page.goto('/en', { waitUntil: 'domcontentloaded' });
    // Rs. 4,182,340,000 from the fixture funnel, formatted by `formatLKR`. It appears
    // twice by design - as the headline figure and on the funnel bar - so this takes
    // the first rather than demanding a unique match.
    await expect(page.getByText('LKR 4,182,340,000').first()).toBeVisible();

    await page.goto('/en/ledger', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('MOCK-BANK_TRANSFER-000000000001').first()).toBeVisible();
  });
});
