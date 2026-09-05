/**
 * The approval queue, and the level rule it shares with the disbursement gate.
 *
 * The property under test: the console tells an approver what a row is still waiting for,
 * and it does so by level rather than by count. Two approvals at the same level are not
 * two levels — a console that counted rows would offer work the gate then refuses, and an
 * approver who learns that refusals are noise is the one habit a human gate cannot afford.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

/** Above `DEFAULT_DISTRICT_THRESHOLD_CENTS` (LKR 500,000), so both levels are required. */
const LARGE = 60_000_000;
/** At or below it, so only DS is required. */
const SMALL = 12_500_000;

function entitlement(overrides: Record<string, unknown> = {}) {
  return {
    id: '018f3c2a-0003-7e90-9c2d-000000000003',
    assessment_id: '018f3c2a-0004-7e90-9c2d-000000000004',
    assessment_ref: 'CLM-251128-A1B2C3',
    household_id: '018f3c2a-0005-7e90-9c2d-000000000005',
    gn_division_code: 'LK-11-03-045',
    category: 'PARTIAL',
    cost_schedule_version: '2025.11',
    calculated_lkr_cents: SMALL,
    calculated_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
    status: 'CALCULATED',
    approved_levels: [],
    released: false,
    ...overrides,
  };
}

test('says which level a row is still waiting for, not just "pending"', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'entitlements', body: [entitlement({ calculated_lkr_cents: LARGE })] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/approvals');

  // Above the threshold, unsigned: both levels outstanding. "Needs District" and "needs
  // DS" go to different people, so a generic "pending" would misroute the work.
  await expect(page.getByText('Needs DS')).toBeVisible();
  await expect(page.getByText('Needs DISTRICT')).toBeVisible();
});

test('a small amount needs only the divisional signature', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'entitlements', body: [entitlement({ calculated_lkr_cents: SMALL })] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/approvals');

  await expect(page.getByText('Needs DS')).toBeVisible();
  await expect(page.getByText('Needs DISTRICT')).toHaveCount(0);
});

test('does not treat two signatures at one level as two levels', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'entitlements',
      // The server returns distinct levels, so this is what a doubly-DS-signed row looks
      // like coming back. It is still short of District.
      body: [entitlement({ calculated_lkr_cents: LARGE, approved_levels: ['DS'] })],
    },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/approvals');

  await expect(page.getByText('Needs DISTRICT')).toBeVisible();
  await expect(page.getByText('Fully approved')).toHaveCount(0);
});

test('marks a row that carries every signature it needs', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'entitlements',
      body: [entitlement({ calculated_lkr_cents: LARGE, approved_levels: ['DS', 'DISTRICT'] })],
    },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/approvals');
  await expect(page.getByText('Fully approved')).toBeVisible();
});

test('requires a second factor before recording a signature', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'entitlements', body: [entitlement()] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/approvals');
  await page.getByRole('row').nth(1).click();

  const sign = page.getByRole('button', { name: /approve as DS/i });
  await expect(sign).toBeDisabled();

  await page.getByLabel(/authenticator code/i).fill('123456');
  await expect(sign).toBeEnabled();

  // Approving is not releasing, and the screen says so before the button.
  await expect(page.getByText(/Approving is not releasing/i)).toBeVisible();
});

test('the release queue lists what is ready, oldest first', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'entitlements',
      body: [entitlement({ approved_levels: ['DS'], status: 'APPROVED' })],
    },
    { match: 'disbursements', body: [] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/disbursements');

  // The screen that used to say "this queue cannot be listed" now lists it.
  await expect(page.getByText('CLM-251128-A1B2C3').first()).toBeVisible();
  await expect(page.getByText(/cannot be listed yet/i)).toHaveCount(0);
});
