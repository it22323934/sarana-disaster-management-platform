/**
 * Chain verification, end to end.
 *
 * The claim this platform makes is that a ledger entry cannot be edited after it is
 * written without that being detectable. These tests cover the three ways the screen
 * could quietly weaken it:
 *
 * - a green result that does not say what range it covers, letting a partial check read
 *   as a whole one;
 * - a red result that says "broken" without saying where;
 * - a green tick over a chain with no external anchor, which is verifiable only against a
 *   database the operator controls.
 */

import { expect, scriptGateway, signInAs, test } from './fixtures';

const ANCHORS_WITH_EXTERNAL = {
  anchors: [
    {
      date: '2025-11-27',
      merkle_root: 'a'.repeat(64),
      entry_count: 412,
      first_seq: 1,
      last_seq: 412,
      prev_anchor_hash: null,
      s3_object_lock_uri: 's3://sarana-anchors/2025-11-27.json',
      published_at: '2025-11-28T00:05:00Z',
    },
  ],
  scheme: { hash: 'sha256', encoding: 'hex', tree: 'rfc6962' },
};

const ANCHORS_WITHOUT_EXTERNAL = {
  anchors: [
    { ...ANCHORS_WITH_EXTERNAL.anchors[0], s3_object_lock_uri: null },
    {
      date: '2025-11-26',
      merkle_root: 'b'.repeat(64),
      entry_count: 108,
      first_seq: 1,
      last_seq: 108,
      prev_anchor_hash: null,
      s3_object_lock_uri: null,
      published_at: '2025-11-27T00:05:00Z',
    },
  ],
  scheme: ANCHORS_WITH_EXTERNAL.scheme,
};

test('a green result names the range it actually checked', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'audit/verify',
      body: { intact: true, checked: 100, from_seq: 1, to_seq: 100, divergence: null },
    },
    { match: 'ledger/anchors', body: ANCHORS_WITH_EXTERNAL },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/audit/chain');
  await page.getByLabel(/from seq/i).fill('1');
  await page.getByLabel(/to seq/i).fill('100');
  await page.getByRole('button', { name: /^verify$/i }).click();

  await expect(page.locator('[data-chain-intact="true"]')).toBeVisible();
  // Without the range, an auditor who checked a hundred entries could walk away believing
  // they had verified the ledger.
  await expect(page.getByText(/100 entries checked, seq 1 to 100/i)).toBeVisible();
});

test('a red result names the exact divergence', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'audit/verify',
      body: {
        intact: false,
        checked: 4200,
        from_seq: 1,
        to_seq: 4200,
        divergence: {
          seq: 4117,
          reason: 'prev_hash does not match the previous entry',
          expected: 'c'.repeat(64),
          found: 'd'.repeat(64),
        },
      },
    },
    { match: 'ledger/anchors', body: ANCHORS_WITH_EXTERNAL },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/audit/chain');
  await page.getByRole('button', { name: /^verify$/i }).click();

  await expect(page.locator('[data-chain-intact="false"]')).toBeVisible();
  // "The chain is broken" is not actionable. The seq, the expectation and what was found
  // are.
  await expect(page.getByText('4117')).toBeVisible();
  await expect(page.getByText(/prev_hash does not match/i)).toBeVisible();
  await expect(page.getByText('c'.repeat(64))).toBeVisible();
});

test('reports days with no external anchor rather than showing a clean chain', async ({
  page,
}) => {
  await signInAs(page);
  await scriptGateway(page, [
    {
      match: 'audit/verify',
      body: { intact: true, checked: 520, from_seq: 1, to_seq: 520, divergence: null },
    },
    { match: 'ledger/anchors', body: ANCHORS_WITHOUT_EXTERNAL },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/audit/chain');

  // The external anchor is the half that survives an operator rewriting the database.
  // Without it, an internally consistent chain is a weaker claim than it looks.
  await expect(page.getByText(/2 days have no external anchor/i)).toBeVisible();
  await expect(page.getByText(/weaker claim than it looks/i)).toBeVisible();
});

test('publishes the hashing scheme, so a verifier needs no source access', async ({ page }) => {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'ledger/anchors', body: ANCHORS_WITH_EXTERNAL },
    { match: 'dispatch-plans', body: [] },
  ]);

  await page.goto('/en/audit/chain');
  await expect(page.getByText('rfc6962')).toBeVisible();
  await expect(page.getByText('sha256')).toBeVisible();
});
