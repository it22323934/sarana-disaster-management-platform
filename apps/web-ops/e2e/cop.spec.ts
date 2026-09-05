/**
 * The common operating picture.
 *
 * Two properties, and the first is the one that was wrong until this suite existed.
 *
 * **The degraded banner follows the server's `assisted` flag, not the presence of a
 * score.** `incident-svc` computes a score for every row from the published rule when
 * nothing has stored one — deliberately, so an unranked incident is never dropped to the
 * bottom of a long queue where nobody reaches it. That means "has a score" is always true,
 * and a console that inferred assisted ranking from it would show a model-ranked queue
 * with no warning while no model was running.
 *
 * **The factor breakdown is one click away and does not replace anything.** An operator
 * comparing row 3 against row 4 has to see both reasons within a few seconds; a detail
 * pane that replaced the context panel would lose the row being compared against.
 */

import { expect, incidentBody, scriptGateway, signInAs, test } from './fixtures';
import type { Page } from '@playwright/test';

/**
 * The queue pane.
 *
 * Scoped, because a reference appears twice on this screen on purpose: once in the queue
 * and once in the map's accessible fallback list, which carries the same facts as the map
 * for anyone who cannot use it. An unscoped locator matches both.
 */
function queuePane(page: Page) {
  return page.getByRole('region', { name: /triage queue/i });
}

function queue(assisted: boolean) {
  return {
    assisted,
    banner: assisted ? null : 'Assisted triage unavailable - manual ordering',
    ordering: assisted ? 'agent-assisted' : 'triage-rules-1',
    entries: [
      {
        ...incidentBody(),
        score: 0.81,
        model_version: 'triage-rules-1',
        factors: { severity: 0.42, people_at_risk: 0.29, location_confidence: 0.1 },
      },
      {
        ...incidentBody({
          id: '018f3c2a-0011-7e90-9c2d-000000000011',
          public_ref: 'INC-251128-B7N4QZ',
          severity: 2,
          people_at_risk: 8,
          lon: null,
          lat: null,
        }),
        score: 0.34,
        model_version: 'triage-rules-1',
        factors: { severity: 0.2, people_at_risk: 0.14 },
      },
    ],
  };
}

test('warns that the ranking is not a model even though every row has a score', async ({
  page,
}) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'incidents/queue', body: queue(false) },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops');

  await expect(page.locator('[data-degraded="agent"]')).toBeVisible();
  // The rule doing the ordering, named. "Manual ordering" alone tells a dispatcher less
  // than the name of the rule that produced the list they are working.
  await expect(page.getByText('triage-rules-1').first()).toBeVisible();
});

test('does not warn when the server says the ranking is assisted', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'incidents/queue', body: queue(true) },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops');

  await expect(queuePane(page).getByText('INC-251128-K4M2XA')).toBeVisible();
  await expect(page.locator('[data-degraded="agent"]')).toHaveCount(0);
});

test('shows why a row outranks another without leaving the screen', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'incidents/queue', body: queue(true) },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops');

  // The score is the trigger. Opening it must not disturb the queue behind it.
  await page.getByRole('button', { name: /why this rank/i }).first().click();

  await expect(page.getByText('people_at_risk')).toBeVisible();
  await expect(page.getByText('0.420')).toBeVisible();
  // The row underneath is still there to compare against.
  await expect(queuePane(page).getByText('INC-251128-B7N4QZ')).toBeVisible();
});

test('keeps an incident with no coordinate in the queue and off the map', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'incidents/queue', body: queue(true) },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops');

  // Second row has no lon/lat. It is a real incident — a call naming a village and
  // nothing more — so it stays in the queue, and the map says how many it cannot place.
  await expect(queuePane(page).getByText('INC-251128-B7N4QZ')).toBeVisible();
  await expect(page.getByText(/1 incident has no coordinate/i)).toBeVisible();
});

test('the pane splitter reports its position to assistive technology', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'incidents/queue', body: queue(true) },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops');

  // A focusable separator is a window splitter, and a splitter without `aria-valuenow`
  // announces "separator" and nothing else — so a keyboard user can move it and never
  // learn whether it moved.
  const splitter = page.getByRole('separator').first();
  await expect(splitter).toHaveAttribute('aria-valuenow', /\d+/);

  const before = await splitter.getAttribute('aria-valuenow');
  await splitter.focus();
  await page.keyboard.press('ArrowRight');
  await expect(splitter).not.toHaveAttribute('aria-valuenow', before ?? '');
});
