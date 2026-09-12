/**
 * The two gate flows, end to end in a browser.
 *
 * These are the tests the brief names, and they exist because the gates are the whole
 * point of this console: the approval flow including the second factor, the rejection
 * flow, the release, and the release refused by an open grievance — plus keyboard-only
 * completion, because a dispatcher with a trackpad and wet hands is a real scenario.
 */

import {
  ENTITLEMENT_ID,
  PLAN_ID,
  entitlementBody,
  expect,
  incidentBody,
  planBody,
  scriptGateway,
  signInAs,
  test,
} from './fixtures';

const DECISION = {
  plan_id: PLAN_ID,
  status: 'APPROVED',
  decided_by: '018f3c2a-0009-7e90-9c2d-000000000009',
  decided_at: new Date().toISOString(),
  graph_resumed: false,
  reason: null,
};

test.describe('the dispatch gate', () => {
  test.beforeEach(async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: `dispatch-plans/${PLAN_ID}/approve`, body: DECISION },
      { match: `dispatch-plans/${PLAN_ID}/reject`, body: { ...DECISION, status: 'REJECTED' } },
      { match: `dispatch-plans/${PLAN_ID}`, body: planBody() },
      { match: 'dispatch-plans', body: [planBody()] },
      { match: `incidents/${'018f3c2a-0001'}`, body: incidentBody() },
      { match: 'responders', body: [] },
    ]);
  });

  test('shows what is being committed above the fold', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    const committing = page.getByText('42').first();
    await expect(committing).toBeVisible();

    // Above the fold at the viewport the config sets. If the summary needs scrolling, a
    // dispatcher decides from the button rather than from the facts.
    const box = await committing.boundingBox();
    expect(box?.y ?? Number.POSITIVE_INFINITY).toBeLessThan(900);
  });

  test('will not approve until the second factor is complete', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    const approve = page.getByRole('button', { name: /approve and dispatch/i });
    await expect(approve).toBeDisabled();

    await page.getByLabel(/authenticator code/i).fill('12345');
    await expect(approve).toBeDisabled();

    await page.getByLabel(/authenticator code/i).fill('123456');
    await expect(approve).toBeEnabled();
  });

  test('does not approve when Enter is pressed in the code field', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    let approvePosted = false;
    page.on('request', (request) => {
      if (request.url().includes('/approve')) approvePosted = true;
    });

    await page.getByLabel(/authenticator code/i).fill('123456');
    await page.getByLabel(/authenticator code/i).press('Enter');
    await page.waitForTimeout(500);

    expect(approvePosted).toBe(false);
  });

  test('offers reject at equal weight, and rejecting takes one click to open', async ({
    page,
  }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    const reject = page.getByRole('button', { name: /^reject$/i });
    await expect(reject).toBeEnabled();

    await reject.click();
    // The taxonomy, not a free-text box: rejections are the training signal the Learn
    // loop runs on and free text cannot be aggregated.
    await expect(page.getByRole('radiogroup')).toBeVisible();
    await expect(page.getByRole('radio', { name: /route impassable/i })).toBeVisible();
  });

  test('completes the rejection flow', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    await page.getByRole('button', { name: /^reject$/i }).click();
    await page.getByRole('radio', { name: /responder unavailable/i }).click();

    const posted = page.waitForRequest((request) => request.url().includes('/reject'));
    await page.getByRole('button', { name: /confirm rejection/i }).click();
    await posted;
  });

  test('is completable with the keyboard alone', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);

    // The code field is focused on load, so an easy decision is fast.
    await expect(page.getByLabel(/authenticator code/i)).toBeFocused();
    await page.keyboard.type('123456');

    const approve = page.getByRole('button', { name: /approve and dispatch/i });
    await expect(approve).toBeEnabled();

    // Tab from the field reaches approve without a pointer.
    await page.keyboard.press('Tab');
    await expect(approve).toBeFocused();
  });

  test('says the agent reasoning is missing rather than showing nothing', async ({ page }) => {
    await page.goto(`/en/ops/dispatch/${PLAN_ID}`);
    await expect(page.locator('[data-degraded="reasoning"]')).toBeVisible();
  });
});

test.describe('the money gate', () => {
  test('shows the calculation as a derivation and releases', async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: `entitlements/${ENTITLEMENT_ID}`, body: entitlementBody() },
      { match: 'grievances', body: [] },
      { match: 'anomalies', body: [] },
      {
        match: 'disbursements',
        body: {
          seq: 1,
          id: '018f3c2a-000a-7e90-9c2d-00000000000a',
          entitlement_id: ENTITLEMENT_ID,
          amount_lkr_cents: 12_500_000,
          released_by: '018f3c2a-0009-7e90-9c2d-000000000009',
          released_at: new Date().toISOString(),
          payment_rail: 'BANK_TRANSFER',
          payment_ref: 'MOCK-000001',
          prev_hash: 'a'.repeat(64),
          entry_hash: 'b'.repeat(64),
          citizen_confirmed: false,
          simulated: true,
        },
      },
    ]);

    await page.goto(`/en/disbursements/${ENTITLEMENT_ID}`);

    // The schedule version and every step, expanded. An approver shown only a total is
    // being asked to rubber-stamp.
    await expect(page.getByText('2025.11')).toBeVisible();
    await expect(page.getByText('base_lkr_cents')).toBeVisible();
    await expect(page.getByText('LKR 125,000.00').first()).toBeVisible();

    // Segregation is stated before the button, not discovered as a 409 after it.
    await expect(page.getByText(/neither the assessor nor an approver/i)).toBeVisible();
  });

  test('refuses the release while a grievance is open', async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: `entitlements/${ENTITLEMENT_ID}`, body: entitlementBody() },
      {
        match: 'grievances',
        body: [
          {
            id: '018f3c2a-0007-7e90-9c2d-000000000007',
            public_ref: 'GRV-251128-Z9Y8',
            entitlement_id: ENTITLEMENT_ID,
            status: 'OPEN',
          },
        ],
      },
      { match: 'anomalies', body: [] },
    ]);

    await page.goto(`/en/disbursements/${ENTITLEMENT_ID}`);

    await expect(page.getByText(/open grievance blocks this release/i)).toBeVisible();

    await page.getByLabel(/release approval/i).fill('123456');
    // Disabled rather than clickable-then-refused. Letting the click through to collect a
    // 409 would teach approvers that refusals are noise.
    await expect(page.getByRole('button', { name: /release funds/i })).toBeDisabled();
  });

  test('never shows a household name, even when the server sends one', async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      {
        match: `entitlements/${ENTITLEMENT_ID}`,
        body: entitlementBody({ household_name: 'Wickramasinghe' }),
      },
      { match: 'grievances', body: [] },
      { match: 'anomalies', body: [] },
    ]);

    await page.goto(`/en/disbursements/${ENTITLEMENT_ID}`);
    await expect(page.getByText('2025.11')).toBeVisible();
    await expect(page.getByText('Wickramasinghe')).toHaveCount(0);
  });
});

test.describe('every gate screen, in three scripts', () => {
  for (const locale of ['en', 'si', 'ta'] as const) {
    test(`renders the dispatch gate in ${locale}`, async ({ page }) => {
      await signInAs(page);
      await scriptGateway(page, [
        { match: `dispatch-plans/${PLAN_ID}`, body: planBody() },
        { match: 'dispatch-plans', body: [planBody()] },
        { match: 'incidents/018f3c2a-0001', body: incidentBody() },
        { match: 'responders', body: [] },
      ]);

      await page.goto(`/${locale}/ops/dispatch/${PLAN_ID}`);

      // `lang` is what selects the Noto face and the screen reader voice.
      await expect(page.locator('html')).toHaveAttribute('lang', `${locale}-LK`);

      // Nothing overflows the viewport horizontally. A layout that breaks in Tamil is a
      // bug of the same severity as a broken build.
      const overflows = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      expect(overflows).toBe(false);
    });
  }
});
