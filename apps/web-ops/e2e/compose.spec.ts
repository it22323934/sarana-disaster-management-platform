/**
 * Alert composition, and the segment gate that is the point of it.
 *
 * The property under test: a Sinhala or Tamil rendering that runs past two segments is
 * visible to the author **while they are still writing**, and blocks the draft. During a
 * national fan-out a third segment is three times the cost, three times the gateway queue,
 * and three parts that can arrive out of order — and the community reading that language
 * is the one whose warning arrives last and incomplete. That is the Ditwah failure
 * arriving through a billing detail.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

const PUBLISHED_TEMPLATE = {
  id: '018f3c2a-000b-7e90-9c2d-00000000000b',
  code: 'FLOOD_WARNING',
  hazard_type: 'FLOOD',
  severity: 'SEVERE',
  urgency: 'EXPECTED',
  certainty: 'LIKELY',
  body: {
    si: '{gn_division_name} ප්‍රදේශයේ ගංවතුර අනතුරු ඇඟවීම. උස් බිමකට යාමට සූදානම් වන්න.',
    ta: '{gn_division_name} பகுதியில் வெள்ள எச்சரிக்கை. உயரமான இடத்திற்கு செல்ல தயாராகுங்கள்.',
    en: 'Flood warning for {gn_division_name}. Prepare to move to higher ground.',
  },
  reviewed_by_si: '018f3c2a-000c-7e90-9c2d-00000000000c',
  reviewed_by_ta: '018f3c2a-000d-7e90-9c2d-00000000000d',
  reviewed_at: '2025-11-20T00:00:00Z',
  version: 1,
  status: 'PUBLISHED',
};

const HAZARD_EVENT = {
  id: '018f3c2a-0030-7e90-9c2d-000000000030',
  type: 'CYCLONE',
  name: { si: 'දිත්වා', ta: 'திட்வா', en: 'Ditwah' },
  source: 'DEPT_METEOROLOGY',
  source_ref: 'DM-2025-11-27',
  declared_at: '2025-11-25T00:00:00Z',
  landfall_at: '2025-11-28T00:00:00Z',
  status: 'ACTIVE',
};

const DRAFT_ONLY_TEMPLATE = {
  ...PUBLISHED_TEMPLATE,
  id: '018f3c2a-000e-7e90-9c2d-00000000000e',
  code: 'FLOOD_WATCH',
  reviewed_by_si: null,
  reviewed_by_ta: null,
  reviewed_at: null,
  status: 'DRAFT',
};

test.describe('the alert composer', () => {
  test('offers only published templates, and says why the others are unavailable', async ({
    page,
  }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'templates', body: [DRAFT_ONLY_TEMPLATE] },
      { match: 'hazard-events', body: [HAZARD_EVENT] },
      { match: 'dispatch-plans', body: [] },
    ]);

    await page.goto('/en/ops/alerts/new');

    // Not "no templates found". The templates exist and are waiting for a human signature
    // in each language — that is the gate working, and the operator needs to know which.
    await expect(page.getByText(/no template is published yet/i)).toBeVisible();
    await expect(page.getByText(/awaiting a signature in Sinhala or Tamil/i)).toBeVisible();
    await expect(page.getByText('FLOOD_WATCH')).toBeVisible();
  });

  test('previews all three languages at once with a segment cost under each', async ({
    page,
  }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'templates', body: [PUBLISHED_TEMPLATE] },
      { match: 'hazard-events', body: [HAZARD_EVENT] },
      { match: 'dispatch-plans', body: [] },
    ]);

    await page.goto('/en/ops/alerts/new');
    await page.getByRole('combobox').click();
    await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

    // All three visible simultaneously. Behind a tab, a three-segment Sinhala rendering is
    // invisible to the person who is the only one who can fix it.
    for (const locale of ['en', 'si', 'ta']) {
      await expect(page.locator(`[data-preview-locale="${locale}"]`)).toBeVisible();
    }

    // English is GSM-7 and fits in one segment; the other two are UCS-2 and cost more for
    // the same sentence, from the alphabet alone.
    await expect(page.locator('[data-preview-locale="en"]')).toHaveAttribute('data-segments', '1');
    const sinhalaSegments = await page
      .locator('[data-preview-locale="si"]')
      .getAttribute('data-segments');
    expect(Number(sinhalaSegments)).toBeGreaterThan(1);
  });

  test('blocks the draft when a rendering runs past two segments', async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'templates', body: [PUBLISHED_TEMPLATE] },
      { match: 'hazard-events', body: [HAZARD_EVENT] },
      { match: 'dispatch-plans', body: [] },
    ]);

    await page.goto('/en/ops/alerts/new');
    await page.getByRole('combobox').click();
    await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

    await page.getByLabel('gn_division_name').fill('Pallekele');
    await page.getByLabel(/GN division codes/i).fill('LK-11-03-045');
    await page.getByRole('combobox').nth(1).click();
    await page.getByRole('option', { name: /Ditwah/ }).click();

    const draft = page.getByRole('button', { name: /create draft/i });
    await expect(draft).toBeEnabled();

    // Push the Sinhala rendering over the limit with free text. The warning has to appear
    // while the author is still writing, not at the dispatch step.
    await page.getByLabel('සිංහල').fill('ට'.repeat(200));

    await expect(page.locator('[data-preview-locale="si"]')).toHaveAttribute(
      'data-segments',
      /[3-9]/,
    );
    await expect(draft).toBeDisabled();
    await expect(page.getByText(/needs more than two segments/i)).toBeVisible();
  });

  test('flags free text as forcing a human sign-off, before it is committed to', async ({
    page,
  }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'templates', body: [PUBLISHED_TEMPLATE] },
      { match: 'hazard-events', body: [HAZARD_EVENT] },
      { match: 'dispatch-plans', body: [] },
    ]);

    await page.goto('/en/ops/alerts/new');
    await page.getByRole('combobox').click();
    await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

    // Stated up front rather than discovered at dispatch.
    await expect(page.getByText(/goes to PENDING_SIGNOFF/i)).toBeVisible();
  });

  test('says a dry run is required before sending', async ({ page }) => {
    await signInAs(page);
    await scriptGateway(page, [
      { match: 'templates', body: [PUBLISHED_TEMPLATE] },
      { match: 'hazard-events', body: [HAZARD_EVENT] },
      { match: 'dispatch-plans', body: [] },
    ]);

    await page.goto('/en/ops/alerts/new');
    await page.getByRole('combobox').click();
    await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

    await expect(page.getByText(/dry run is required before sending/i)).toBeVisible();
  });
});

test('will not draft without naming the hazard event it is about', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'templates', body: [PUBLISHED_TEMPLATE] },
    { match: 'hazard-events', body: [HAZARD_EVENT] },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops/alerts/new');
  await page.getByRole('combobox').first().click();
  await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

  await page.getByLabel('gn_division_name').fill('Pallekele');
  await page.getByLabel(/GN division codes/i).fill('LK-11-03-045');

  // Everything else filled, no event chosen. `POST /alerts` requires it, and a draft that
  // names no event is one nobody can tie to a warning later.
  await expect(page.getByRole('button', { name: /create draft/i })).toBeDisabled();
});

test('creates a draft and says it still needs sign-off and a dry run', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'templates', body: [PUBLISHED_TEMPLATE] },
    { match: 'hazard-events', body: [HAZARD_EVENT] },
    {
      match: 'alerts',
      body: {
        id: '018f3c2a-0031-7e90-9c2d-000000000031',
        cap_identifier: 'urn:oid:2.49.0.1.144.0.2025.11.28.0001',
        status: 'DRAFT',
        requires_human_signoff: false,
      },
    },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/ops/alerts/new');
  await page.getByRole('combobox').first().click();
  await page.getByRole('option', { name: /FLOOD_WARNING/ }).click();

  await page.getByLabel('gn_division_name').fill('Pallekele');
  await page.getByLabel(/GN division codes/i).fill('LK-11-03-045');
  await page.getByRole('combobox').nth(1).click();
  await page.getByRole('option', { name: /Ditwah/ }).click();

  const posted = page.waitForRequest(
    (request) => request.url().includes('/gateway/alerts') && request.method() === 'POST',
  );
  await page.getByRole('button', { name: /create draft/i }).click();
  const request = await posted;

  const body = JSON.parse(request.postData() ?? '{}');
  expect(body.hazard_event_id).toBe(HAZARD_EVENT.id);
  expect(body.gn_division_codes).toEqual(['LK-11-03-045']);

  // Drafting is not sending. One button that did both is how a national fan-out happens
  // by accident.
  await expect(page.getByText(/still needs sign-off and a dry run/i)).toBeVisible();
});
