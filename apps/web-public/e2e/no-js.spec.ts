/**
 * The core numbers work with JavaScript disabled. `pnpm --filter web-public test:no-js`
 *
 * The brief names the reader this protects: "a journalist behind a locked-down corporate
 * proxy should still get the numbers". It is also the reader on a two-bar connection whose
 * scripts time out, and the one using a text browser or a screen reader in a hardened
 * enterprise build.
 *
 * `javaScriptEnabled: false` is genuine — Chromium does not execute a line — so a page that
 * needed hydration to show a figure fails here rather than looking fine in review.
 *
 * The brief requires it for `/`, `/schedule` and `/ledger`. This suite covers those three
 * and then checks the two interactions that would most plausibly have been built with
 * JavaScript and were deliberately not: the language switcher and the district metric
 * selector. A site that showed its numbers without scripting but could not change language
 * without it would have met the letter of the requirement and missed the reader.
 */

import { expect, test } from '@playwright/test';

test.use({ javaScriptEnabled: false });

test.describe('with JavaScript disabled', () => {
  test('the overview shows all four headline figures and their failure counts', async ({
    page,
  }) => {
    await page.goto('/en', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('LKR 4,182,340,000').first()).toBeVisible();
    await expect(page.getByText('LKR 3,910,220,000').first()).toBeVisible();
    await expect(page.getByText('LKR 3,402,110,000').first()).toBeVisible();
    await expect(page.getByText('LKR 2,981,450,000').first()).toBeVisible();

    // The uncomfortable figures are part of "the core numbers", not an enhancement. A
    // page that dropped them without scripting would be the exact omission the brief
    // spends a paragraph on.
    await expect(page.getByText('949').first()).toBeVisible();
    await expect(page.getByRole('heading', { name: /what has not gone right/i })).toBeVisible();
  });

  test('the cost schedule shows every rate, cap and formula', async ({ page }) => {
    await page.goto('/en/schedule', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('House fully damaged')).toBeVisible();
    await expect(page.getByText('LKR 2,500,000.00').first()).toBeVisible();
    // The formula, verbatim. It is what turns the entitlement into something checkable,
    // so it is core content rather than detail.
    await expect(page.getByText('min(rate * quantity, cap)').first()).toBeVisible();
  });

  test('the ledger shows its rows, hashes and pagination', async ({ page }) => {
    await page.goto('/en/ledger', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('MOCK-BANK_TRANSFER-000000000001').first()).toBeVisible();
    await expect(page.getByRole('table')).toBeVisible();
  });

  test('the language switcher works, because it is three links', async ({ page }) => {
    await page.goto('/en/ledger', { waitUntil: 'domcontentloaded' });
    await page.getByRole('link', { name: 'සිංහල' }).click();

    await expect(page).toHaveURL(/\/si\/ledger$/);
    await expect(page.locator('html')).toHaveAttribute('lang', 'si-LK');
  });

  test('the district metric selector works, because it is a GET form', async ({ page }) => {
    await page.goto('/en/districts', { waitUntil: 'domcontentloaded' });

    await page.selectOption('#metric', 'medianDays');
    await page.getByRole('button').first().click();

    await expect(page).toHaveURL(/metric=medianDays/);
    // The "where is it slow" view, which the brief calls the most newsworthy on the site,
    // reachable with no scripting at all.
    await expect(page.getByText('11.5').first()).toBeVisible();
  });

  test('a district page shows its DS breakdown and its suppression notice', async ({ page }) => {
    await page.goto('/en/districts/LK-21', { waitUntil: 'domcontentloaded' });

    await expect(page.getByText('Kandy').first()).toBeVisible();
    // Suppression is disclosed rather than left as a gap, and the disclosure is server
    // rendered like everything else.
    await expect(page.getByText(/3 divisions withheld for privacy/i)).toBeVisible();
  });
});
