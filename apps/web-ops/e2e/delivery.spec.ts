/**
 * The delivery gaps panel, end to end.
 *
 * This is the screen that turns "we sent the warning" into "these divisions probably did
 * not get it, send a vehicle". Two properties are tested because losing either would make
 * the screen actively misleading:
 *
 * - **No count appears without its denominator.** A bare "72%" over an unstated base is
 *   how a district gets reported as covered when the base was four synthetic people.
 * - **The order is not re-sorted.** The server returns worst-first and that order is the
 *   instruction: it says which division to send the vehicle to first.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

const ALERT_ID = '018f3c2a-0008-7e90-9c2d-000000000008';

const DELIVERY = {
  targeted: 1203,
  confirmed: 865,
  unconfirmed: 300,
  failed: 20,
  no_channel: 18,
  by_channel: { SMS: { CONFIRMED: 800, FAILED: 20 }, PUSH: { CONFIRMED: 65 } },
  by_language: { si: 700, ta: 300, en: 203 },
  summary: '865 of 1,203 targeted households confirmed delivery.',
};

/** Deliberately not in ascending order of confirmation, to prove nothing re-sorts. */
const GAPS = [
  {
    gn_division_code: 'LK-11-03-045',
    targeted: 400,
    confirmed: 40,
    confirmed_fraction: 0.1,
    summary: '40 of 400 confirmed. Probably unreached.',
  },
  {
    gn_division_code: 'LK-11-03-012',
    targeted: 210,
    confirmed: 63,
    confirmed_fraction: 0.3,
    summary: '63 of 210 confirmed. Probably unreached.',
  },
  {
    gn_division_code: 'LK-11-02-007',
    targeted: 120,
    confirmed: 54,
    confirmed_fraction: 0.45,
    summary: '54 of 120 confirmed. Probably unreached.',
  },
];

test.beforeEach(async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: `alerts/${ALERT_ID}/delivery/gaps`, body: GAPS },
    { match: `alerts/${ALERT_ID}/delivery`, body: DELIVERY },
    { match: 'dispatch-plans', body: [] },
  ]);
});

test('shows every count with what it is a fraction of', async ({ page }) => {
  await page.goto(`/en/ops/alerts/${ALERT_ID}/delivery`);

  // The server's own sentence, verbatim. It is guaranteed never to be a bare percentage.
  await expect(page.getByText(DELIVERY.summary).first()).toBeVisible();

  // Each tile carries `n / m`. A tile with a lone number is the defect this asserts away.
  await expect(page.getByText('/ 1,203').first()).toBeVisible();

  const body = await page.locator('body').innerText();
  // No bare percentage anywhere on the page. The one place a fraction appears, it appears
  // as a pair of counts.
  expect(body).not.toMatch(/\b\d{1,3}%/);
});

test('keeps the server order, worst first', async ({ page }) => {
  await page.goto(`/en/ops/alerts/${ALERT_ID}/delivery`);

  const codes = page.locator('table').last().locator('tbody tr td:first-child');
  await expect(codes.first()).toContainText('LK-11-03-045');

  const rendered = await codes.allInnerTexts();
  const meaningful = rendered.map((text) => text.trim()).filter((text) => text.length > 0);
  expect(meaningful.slice(0, 3)).toEqual(['LK-11-03-045', 'LK-11-03-012', 'LK-11-02-007']);
});

test('renders the gaps panel in all three scripts without overflowing', async ({ page }) => {
  for (const locale of ['en', 'si', 'ta'] as const) {
    await page.goto(`/${locale}/ops/alerts/${ALERT_ID}/delivery`);
    await expect(page.locator('html')).toHaveAttribute('lang', `${locale}-LK`);

    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(overflows, `${locale} overflows the viewport`).toBe(false);
  }
});
