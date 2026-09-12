/**
 * The trilingual template review gate.
 *
 * This is the gate that stands between twelve machine-translated life-safety messages and
 * a district. All twelve seeded templates are `DRAFT` with no signatures, deliberately —
 * seeding them as `PUBLISHED` to make a demo flow smoothly would put every one of them a
 * single API call from being dispatched.
 *
 * What these tests protect: publication is unreachable until both native signatures are
 * present, and the reviewer signs one named language at a time.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

const TEMPLATE_ID = '018f3c2a-000b-7e90-9c2d-00000000000b';

function template(overrides: Record<string, unknown> = {}) {
  return {
    id: TEMPLATE_ID,
    code: 'FLOOD_WARNING',
    hazard_type: 'FLOOD',
    severity: 'SEVERE',
    urgency: 'EXPECTED',
    certainty: 'LIKELY',
    body: {
      si: 'පල්ලේකැලේ ප්‍රදේශයේ ගංවතුර අනතුරු ඇඟවීම.',
      ta: 'பள்ளேகலை பகுதியில் வெள்ள எச்சரிக்கை.',
      en: 'Flood warning for Pallekele.',
    },
    reviewed_by_si: null,
    reviewed_by_ta: null,
    reviewed_at: null,
    version: 1,
    status: 'DRAFT',
    ...overrides,
  };
}

test('publication is unreachable while either signature is missing', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'cost-schedules', body: [] },
    { match: 'templates', body: [template()] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/admin');

  await expect(page.locator('[data-template-status="DRAFT"]')).toBeVisible();
  await expect(page.getByRole('button', { name: /^publish$/i })).toBeDisabled();
  await expect(page.getByText(/needs both signatures/i)).toBeVisible();
});

test('one signature is still not enough', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'cost-schedules', body: [] },
    {
      match: 'templates',
      body: [template({ reviewed_by_si: '018f3c2a-000c-7e90-9c2d-00000000000c' })],
    },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/admin');

  // Sinhala signed, Tamil not. This is the exact state the Ditwah failure was: the
  // message went out in Sinhala and English, and Tamil-speaking communities did not get
  // the warning.
  await expect(page.getByText(/සිංහල signed/)).toBeVisible();
  await expect(page.getByText(/தமிழ் unsigned/)).toBeVisible();
  await expect(page.getByRole('button', { name: /^publish$/i })).toBeDisabled();
});

test('publication opens only once both signatures are present', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'cost-schedules', body: [] },
    {
      match: 'templates',
      body: [
        template({
          reviewed_by_si: '018f3c2a-000c-7e90-9c2d-00000000000c',
          reviewed_by_ta: '018f3c2a-000d-7e90-9c2d-00000000000d',
          reviewed_at: '2025-11-20T00:00:00Z',
        }),
      ],
    },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/admin');

  await expect(page.getByRole('button', { name: /^publish$/i })).toBeEnabled();
  await expect(page.getByText(/needs both signatures/i)).toHaveCount(0);
});

test('signs one named language at a time, never both at once', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'cost-schedules', body: [] },
    { match: `templates/${TEMPLATE_ID}/review`, body: { ...template(), status: 'DRAFT' } },
    { match: 'templates', body: [template()] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/admin');

  const posted = page.waitForRequest((request) => request.url().includes('/review'));
  // Two separate buttons, each naming its language in that language. Someone who reads
  // both still has to say which one they are signing for.
  await page.getByRole('button', { name: /සිංහල/ }).click();
  const request = await posted;

  expect(JSON.parse(request.postData() ?? '{}')).toEqual({ language: 'si' });
  // The reviewer's identity is never in the body — it comes from the token, because a
  // review somebody else can attribute to you is not a review.
  expect(request.postData()).not.toContain('reviewer');
});

test('renders the body in each language with its own lang attribute', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'cost-schedules', body: [] },
    { match: 'templates', body: [template()] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/admin');

  // A reviewer reading Tamil rendered in the Latin fallback is reviewing something other
  // than what ships.
  await expect(page.locator('p[lang="ta-LK"]')).toContainText('வெள்ள எச்சரிக்கை');
  await expect(page.locator('p[lang="si-LK"]')).toContainText('ගංවතුර අනතුරු');
});
