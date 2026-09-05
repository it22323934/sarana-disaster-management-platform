/**
 * The degraded states, which the brief says to design first.
 *
 * Two of them are tested here and they fail in opposite directions, which is why both
 * need a test:
 *
 * **Agent service down.** The queue still works and is still ordered — `incident-svc`
 * scores every unranked row from the published rule rather than dropping it to the bottom
 * of a long queue where nobody reaches it. The danger is the reverse of an outage: the
 * screen looks completely normal. So the banner has to appear, and it has to appear on the
 * strength of the `assisted` flag rather than on whether rows carry a score — because they
 * always do.
 *
 * **Backend unreachable.** A stale map beats a blank one during a cyclone, so the last
 * picture stays on screen. The danger there is the opposite: an operator works a
 * fifteen-minute-old queue believing it is current. So the age is stated prominently, and
 * a failure with nothing cached shows an error rather than an empty queue that reads as
 * "no incidents".
 */

import { expect, incidentBody, scriptGateway, signInAs, test } from './fixtures';

function queueBody(overrides: Record<string, unknown> = {}) {
  return {
    assisted: false,
    banner: 'Assisted triage unavailable - manual ordering',
    ordering: 'triage-rules-1',
    entries: [
      {
        ...incidentBody(),
        // A score on every row, which is what `incident-svc` actually returns when no
        // agent has run. Inferring "assisted" from this would always say yes.
        score: 0.71,
        model_version: 'triage-rules-1',
        factors: { severity: 0.4, people_at_risk: 0.31 },
      },
    ],
    ...overrides,
  };
}

test.describe('with the agent service stopped', () => {
  test.beforeEach(async ({ page }) => {
    await signInAs(page);
  });

  test('renders a usable queue and says the ordering is not a model', async ({ page }) => {
    await scriptGateway(page, [
      { match: 'incidents/queue', body: queueBody() },
      { match: 'audit', body: [] },
      { match: 'responders', body: [] },
      { match: 'impact-forecasts', body: [] },
      { match: 'entitlements', body: [] },
      { match: 'dispatch-plans', body: [] },
    ]);
    await page.goto('/en/ops');

    // The queue is there and workable. `.first()` because the reference legitimately
    // appears twice: once in the queue row and once in the map's accessible fallback
    // list, which is the same content rather than a summary of it.
    await expect(page.getByText('INC-251128-K4M2XA').first()).toBeVisible();

    // And it is labelled. This is the single most misleading thing this console could do
    // if it were missing: a dispatcher working a rule-ordered queue believing a model
    // ordered it.
    await expect(page.locator('[data-degraded="agent"]')).toBeVisible();
    await expect(page.getByText('triage-rules-1').first()).toBeVisible();
  });

  test('still warns when every row carries a score', async ({ page }) => {
    // The regression this pins: `assisted: false` with a score on every row must still
    // warn. The console once inferred assistance from the presence of a score, and that
    // inference can never be false.
    await scriptGateway(page, [
      { match: 'incidents/queue', body: queueBody({ assisted: false }) },
      { match: 'audit', body: [] },
      { match: 'responders', body: [] },
      { match: 'impact-forecasts', body: [] },
      { match: 'entitlements', body: [] },
      { match: 'dispatch-plans', body: [] },
    ]);
    await page.goto('/en/ops');
    await expect(page.locator('[data-degraded="agent"]')).toBeVisible();
  });

  test('drops the banner when an agent really did rank the queue', async ({ page }) => {
    await scriptGateway(page, [
      { match: 'incidents/queue', body: queueBody({ assisted: true, ordering: 'triage-v2' }) },
      { match: 'audit', body: [] },
      { match: 'responders', body: [] },
      { match: 'impact-forecasts', body: [] },
      { match: 'entitlements', body: [] },
      { match: 'dispatch-plans', body: [] },
    ]);
    await page.goto('/en/ops');
    await expect(page.locator('[data-degraded="agent"]')).toHaveCount(0);
  });
});

test.describe('with the platform unreachable and nothing cached', () => {
  test('says the request failed rather than showing an empty queue', async ({ page }) => {
    // An empty queue during an outage reads as "no incidents", which is the most dangerous
    // thing this screen can say. With no cached picture to prefer, the error is honest.
    await signInAs(page);
    await page.route('**/gateway/**', async (route) => {
      await route.fulfill({
        status: 502,
        contentType: 'application/json',
        body: JSON.stringify({
          type: 'https://sarana.lk/errors/upstream-unavailable',
          title: 'The platform could not be reached',
          status: 502,
          correlation_id: 'corr-degraded-1',
          errors: [],
        }),
      });
    });
    await page.goto('/en/ops');

    await expect(page.getByRole('alert').first()).toBeVisible();
    // The correlation id is on screen, not behind a details toggle: it is the only thing
    // connecting what the operator saw to what the server logged.
    await expect(page.getByText('corr-degraded-1')).toBeVisible();
  });
});
