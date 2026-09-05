/**
 * The dispatch gate with the agent's reasoning attached.
 *
 * Build file 20 requires the gate screen to show the per-incident factor breakdown
 * "expanded by default. Not behind a disclosure. If the operator has to click to see the
 * reasoning, they will stop looking at it by hour six" — and to show `unservable`
 * "prominent, not a footnote. This is often the most decision-relevant thing on the page."
 *
 * Those two properties are what these tests hold. The reasoning itself has been in
 * `dispatch_plan.route` since file 16; what was missing was a response model that exposed
 * it, so the screen used to render a degraded banner in every case. That banner still
 * exists and still matters — it is the honest answer for a plan nothing recorded a reason
 * for — so the last test here pins the *distinction*, which is the part that is easy to
 * lose: null reasoning and empty reasoning are different claims.
 */

import {
  PLAN_ID,
  UNSERVABLE_INCIDENT_ID,
  expect,
  incidentBody,
  planBody,
  reasoningBody,
  responderBody,
  scriptGateway,
  signInAs,
  test,
} from './fixtures';

async function openGateWith(
  page: Parameters<typeof scriptGateway>[0],
  reasoning: unknown,
): Promise<void> {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: `dispatch-plans/${PLAN_ID}`,
      body: planBody({ langgraph_thread_id: 'thread-1', reasoning }),
    },
    { match: 'dispatch-plans', body: [planBody()] },
    { match: 'incidents/018f3c2a-0001', body: incidentBody() },
    { match: 'responders', body: [responderBody()] },
  ]);
  await page.goto(`/en/ops/dispatch/${PLAN_ID}`);
}

test.describe('the gate with reasoning attached', () => {
  test('renders the factor breakdown without anything being clicked', async ({ page }) => {
    await openGateWith(page, reasoningBody());

    // The contribution names and their values, on screen at load. No disclosure to open.
    await expect(page.getByText('people_at_risk')).toBeVisible();
    await expect(page.getByText('0.410')).toBeVisible();
    await expect(page.getByText('severity', { exact: true })).toBeVisible();

    // And the sentence the agent wrote for this incident.
    await expect(
      page.getByText('42 people at risk in a division with road access lost'),
    ).toBeVisible();
  });

  test('shows the unservable incident prominently, above the decision', async ({ page }) => {
    await openGateWith(page, reasoningBody());

    const unservable = page.locator('[data-unservable-count]');
    await expect(unservable).toBeVisible();
    await expect(unservable).toHaveAttribute('data-unservable-count', '1');
    await expect(unservable).toContainText('NO_CAPABLE_RESPONDER');
    await expect(unservable).toContainText('no boat-capable team within range');
    await expect(unservable).toContainText(UNSERVABLE_INCIDENT_ID.slice(0, 8));

    // Above the approve control. A dispatcher who reaches the button before the list of
    // people nobody is going to has been shown them too late.
    const unservableBox = await unservable.boundingBox();
    const approveBox = await page
      .getByRole('button', { name: /approve and dispatch/i })
      .boundingBox();
    expect(unservableBox?.y ?? 0).toBeLessThan(approveBox?.y ?? 0);
  });

  test('names the solver and how the prose was written', async ({ page }) => {
    await openGateWith(page, reasoningBody());

    // A sentence with no attribution is one a dispatcher cannot weigh. "TEMPLATE" and a
    // model name mean different things about how much to trust it.
    await expect(page.getByText('TEMPLATE')).toBeVisible();
    await expect(page.getByText(/ORTOOLS/)).toBeVisible();
  });

  test('does not show the degraded banner when a reason was recorded', async ({ page }) => {
    await openGateWith(page, reasoningBody());
    await expect(page.locator('[data-degraded="reasoning"]')).toHaveCount(0);
  });

  test('shows the degraded banner when nothing recorded a reason', async ({ page }) => {
    // Null, not empty. This is the honest state for a plan proposed by something other
    // than the triage agent, and the screen has to distinguish it from "the agent weighed
    // nothing" - which is what an empty factor list under a "why" heading would say.
    await openGateWith(page, null);
    await expect(page.locator('[data-degraded="reasoning"]')).toBeVisible();
    await expect(page.locator('[data-unservable-count]')).toHaveCount(0);
  });

  test('renders the responder by its organisation, not by an invented callsign', async ({
    page,
  }) => {
    // The console assumed a `callsign` field this service has never had. The assumption
    // failed at the zod boundary and quietly emptied this list, so the plan looked like it
    // had no responders on the one screen where that matters.
    await openGateWith(page, reasoningBody());
    await expect(page.getByText('Sri Lanka Navy')).toBeVisible();
  });
});
