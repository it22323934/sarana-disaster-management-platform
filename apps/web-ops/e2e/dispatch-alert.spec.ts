/**
 * `/ops/alerts/[id]` — the mandatory dry run, and the send behind it.
 *
 * "Dry-run is mandatory before send. The confirm screen shows exact target count,
 * per-channel breakdown, estimated cost, and per-language split. A send that would reach
 * more than the configured cap requires a typed reason."
 *
 * The dry run is the only one of those rules the *console* has to enforce, and that is
 * worth being precise about: `alerting-svc` will accept a dispatch without one, because a
 * dry run takes no transport at all and nothing server-side knows whether anybody looked.
 * So this is the one place the rule can live, and these tests are the only thing holding
 * it.
 */

import {
  ALERT_ID,
  alertBody,
  dryRunBody,
  expect,
  scriptGateway,
  signInAs,
  test,
} from './fixtures';

async function openDraft(
  page: Parameters<typeof scriptGateway>[0],
  options: { dryRun?: unknown; alert?: unknown } = {},
): Promise<void> {
  await signInAs(page);
  await scriptGateway(page, [
    { match: `alerts/${ALERT_ID}/dispatch`, body: options.dryRun ?? dryRunBody() },
    { match: `alerts/${ALERT_ID}`, body: options.alert ?? alertBody() },
    { match: 'alerts', body: [] },
  ]);
  await page.goto(`/en/ops/alerts/${ALERT_ID}`);
}

test.describe('the mandatory dry run', () => {
  test('leaves send unavailable until a dry run has been performed', async ({ page }) => {
    await openDraft(page);

    const send = page.getByRole('button', { name: /^send this alert$/i });
    await expect(send).toBeDisabled();
    await expect(page.getByText(/run the dry run first/i)).toBeVisible();

    await page.getByRole('button', { name: /run the dry run/i }).click();
    await expect(page.locator('[data-dry-run-targeted]')).toBeVisible();
    await expect(send).toBeEnabled();
  });

  test('shows the target count, the per-channel and per-language split, and the cost', async ({
    page,
  }) => {
    await openDraft(page);
    await page.getByRole('button', { name: /run the dry run/i }).click();

    const result = page.locator('[data-dry-run-targeted]');
    await expect(result).toHaveAttribute('data-dry-run-targeted', '1203');
    await expect(result).toContainText('1,203');
    // Per channel and per language, both, because a fan-out that is 1,203 SMS and 402
    // pushes costs and behaves differently from one that is the reverse.
    await expect(result).toContainText('SMS');
    await expect(result).toContainText('PUSH');
    await expect(result).toContainText('Rs. 2,105.25');
  });

  test('clears a stale plan when the dry run is re-run', async ({ page }) => {
    // A count from ten minutes ago is worse than no count, because it looks like
    // diligence. The result is cleared before the new call rather than after it.
    await openDraft(page);
    await page.getByRole('button', { name: /run the dry run/i }).click();
    await expect(page.locator('[data-dry-run-targeted]')).toBeVisible();

    await page.getByRole('button', { name: /run it again/i }).click();
    await expect(page.locator('[data-dry-run-targeted]')).toBeVisible();
  });

  test('requires a typed reason when the send is over the cap', async ({ page }) => {
    await openDraft(page, { dryRun: dryRunBody({ targeted: 84_000, exceeds_cap: true }) });
    await page.getByRole('button', { name: /run the dry run/i }).click();

    await expect(page.getByText(/above the .* cap/i)).toBeVisible();
    const send = page.getByRole('button', { name: /^send this alert$/i });
    await expect(send).toBeDisabled();

    await page.getByLabel(/why this send should proceed/i).fill('Confirmed with DMC duty officer.');
    await expect(send).toBeEnabled();
  });

  test('blocks the send while an alert with free text is unsigned', async ({ page }) => {
    // The soft third gate. Free text forces a named human to sign, and the console shows
    // it as a blocking state rather than as a note at the bottom of the screen.
    await openDraft(page, {
      alert: alertBody({ status: 'PENDING_SIGNOFF', requires_human_signoff: true }),
    });
    await page.getByRole('button', { name: /run the dry run/i }).click();

    await expect(page.getByText(/a human must sign this off first/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /^send this alert$/i })).toBeDisabled();
  });

  test('states the quiet-hours rule, not only its verdict', async ({ page }) => {
    await openDraft(page);
    // The rule itself is on screen in every state. An operator who can read it can predict
    // it next time; one shown only a verdict re-learns it every night.
    const notice = page.locator('[data-quiet-hours]');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('22:00');
    await expect(notice).toContainText('05:00');
    await expect(notice).toContainText('SMS');
  });
});
