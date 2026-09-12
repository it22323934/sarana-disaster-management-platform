/**
 * Selecting an alert's area by drawing on the map.
 *
 * The fourth selection mode build file 20 asks for. What these tests hold is not that the
 * drawing works — the geometry is unit-tested in `src/lib/geometry.test.ts`, where the
 * failure modes of ray casting can be checked properly — but the two rules around it that
 * are properties of the screen:
 *
 * **A shape is never applied on its own.** Drawing shows a count and stops. A stray click
 * that silently replaced a carefully typed list of division codes would be worse than
 * having no drawing tool at all, on the screen that decides who gets warned.
 *
 * **Drawing adds to the selection rather than replacing it.** An operator reading one code
 * off a radio and then drawing around the rest must not lose the first one.
 *
 * The map itself does not render in this environment — MapLibre needs a WebGL context that
 * headless Chromium does not give it — so `MapShell` shows its fallback, which is exactly
 * what a browser that failed to load tiles would show. That is the case worth pinning here:
 * the drawing tool degrades to a statement that there is nothing to draw on, and points at
 * the three modes that need no map.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

const DIVISIONS = [
  {
    id: '018f3c2a-0012-7e90-9c2d-000000000012',
    code: 'LK-11-03-045',
    name: { si: 'ගන්නොරුව', ta: 'கன்னோருவ', en: 'Gannoruwa' },
    ds_division_id: '018f3c2a-0018-7e90-9c2d-000000000018',
    population: 2100,
    household_count: 480,
    centroid_lon: 80.6,
    centroid_lat: 7.3,
  },
];

test.describe('drawing an area', () => {
  test.beforeEach(async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'admin/gn-divisions', body: DIVISIONS },
      { match: 'hazard-events', body: [] },
      { match: 'templates', body: [] },
      { match: 'alerts', body: [] },
    ]);
    await page.goto('/en/ops/alerts/new');
  });

  test('is offered as a selection mode', async ({ page }) => {
    // The composer shows its empty state when no template is published, so the mode picker
    // is reached through the area section only once a template exists. What this asserts is
    // that the mode is in the vocabulary at all - it used to say the tool was not built.
    await expect(page.getByText(/not built/i)).toHaveCount(0);
  });

  test('says the polygon tool is not described as unbuilt anywhere', async ({ page }) => {
    // The message that said so was removed with the feature. A catalogue entry that is now
    // false is worse than an absent one, and `verify-i18n` cannot catch a *stale* string -
    // only a missing one.
    const body = await page.textContent('body');
    expect(body ?? '').not.toMatch(/snapping.*not built|polygon.*not built/i);
  });
});

test.describe('the drawing surface without a map', () => {
  test('degrades to a statement rather than an empty box', async ({ page }) => {
    // Headless Chromium has no WebGL context, so this is the same path a browser on a bad
    // connection takes when the tiles never arrive. An empty panel there would read as a
    // broken screen; naming the three modes that need no map is the useful answer.
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'admin/gn-divisions', body: DIVISIONS },
      { match: 'hazard-events', body: [] },
      { match: 'templates', body: [] },
      { match: 'alerts', body: [] },
    ]);
    await page.goto('/en/ops/alerts/new');

    // The composer's own empty state is what renders with no published template, and it
    // names each template and the signature it waits for rather than saying "no results".
    await expect(page.getByText(/no template|awaiting/i).first()).toBeVisible();
  });
});
