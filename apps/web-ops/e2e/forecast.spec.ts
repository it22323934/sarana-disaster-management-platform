/**
 * `/ops/forecast` — the screen that used to say it was not built.
 *
 * It rendered `NotBuilt` for the whole of file 20 because nothing exposed
 * `hazard.impact_forecast`, which has existed since file 04. The forecast agent was
 * writing to a surface no human could read.
 *
 * The property these tests hold is the one this screen shares with the triage queue: **a
 * rule-derived class is never shown as a model's**. The forecast engine is a rule-threshold
 * engine today, and a threshold crossing presented as a prediction is trusted more than it
 * has earned. Every row says which it is, and the screen says it again above the table
 * when nothing on it came from a model.
 */

import {
  HAZARD_EVENT_ID,
  expect,
  forecastBody,
  scriptGateway,
  signInAs,
  test,
} from './fixtures';

const HAZARD_EVENT = {
  id: HAZARD_EVENT_ID,
  type: 'CYCLONE',
  name: { si: 'දිත්වා', ta: 'திட்வா', en: 'Ditwah' },
  source: 'DMC',
  source_ref: 'DMC-2025-11-28',
  declared_at: new Date(Date.now() - 72 * 3_600_000).toISOString(),
  landfall_at: new Date(Date.now() - 6 * 3_600_000).toISOString(),
  status: 'RESPONSE',
};

async function openForecast(
  page: Parameters<typeof scriptGateway>[0],
  rows: unknown[],
  triggers: unknown[] = [],
): Promise<void> {
  await signInAs(page);
  await scriptGateway(page, [
    { match: 'impact-forecasts/history', body: rows },
    { match: 'impact-forecasts', body: rows },
    { match: 'anticipatory-triggers', body: triggers },
    { match: 'hazard-events', body: [HAZARD_EVENT] },
  ]);
  await page.goto('/en/ops/forecast');
}

test.describe('the impact forecast board', () => {
  test('is built, and does not say it is not', async ({ page }) => {
    await openForecast(page, [forecastBody()]);
    await expect(page.getByRole('heading', { name: /impact forecast/i })).toBeVisible();
    await expect(page.getByText(/does not exist yet/i)).toHaveCount(0);
  });

  test('says every row came from a published threshold rather than a model', async ({
    page,
  }) => {
    await openForecast(page, [forecastBody()]);
    // On the row, and again as a banner above the table. The same failure the triage
    // queue's `assisted` flag prevents, one loop further upstream.
    await expect(page.getByText('Published threshold').first()).toBeVisible();
    await expect(page.locator('[data-degraded="agent"]')).toBeVisible();
  });

  test('drops the banner when a model produced the rows', async ({ page }) => {
    await openForecast(page, [
      forecastBody({ method: 'MODEL', model_version: 'impact-v2' }),
    ]);
    await expect(page.locator('[data-degraded="agent"]')).toHaveCount(0);
    await expect(page.getByText('impact-v2')).toBeVisible();
  });

  test('leads with the divisions at the evacuate line and the households behind them', async ({
    page,
  }) => {
    await openForecast(page, [
      forecastBody(),
      forecastBody({
        id: 'second',
        gn_division_code: 'LK-11-03-046',
        impact_class: 2,
        expected_households_affected: 30,
      }),
    ]);

    // The class-4 division sorts first: the operator reads the top of this table under
    // time pressure and it has to lead with what the decision turns on.
    const codes = page.locator('[data-sarana-datum]').filter({ hasText: /^LK-11-03-04/ });
    await expect(codes.first()).toHaveText('LK-11-03-045');
    await expect(page.getByText('510')).toBeVisible();
  });

  test('renders every driver, including one it has never seen', async ({ page }) => {
    // A forecast with no account of what moved it is not reviewable, which is why the
    // table requires `drivers` to be non-empty. Dropping an unrecognised key would remove
    // the reason from the record whose whole purpose is carrying one.
    await openForecast(page, [
      forecastBody({ drivers: { rainfall_mm_24h: 214, a_term_added_last_week: 0.42 } }),
    ]);
    await page.getByText('LK-11-03-045').first().click();
    await expect(page.getByText('a_term_added_last_week')).toBeVisible();
    await expect(page.getByText('0.42')).toBeVisible();
  });

  test('shows a fired trigger with what it actually did', async ({ page }) => {
    await openForecast(page, [forecastBody()], [
      {
        id: 'trigger-1',
        hazard_event_id: HAZARD_EVENT_ID,
        gn_division_code: 'LK-11-03-045',
        condition: { rainfall_mm_24h: { gte: 200 } },
        fired_at: new Date(Date.now() - 3_600_000).toISOString(),
        action_taken: 'ALERT_DRAFTED',
        forecast_id: null,
        notes: null,
        created_at: new Date(Date.now() - 48 * 3_600_000).toISOString(),
      },
    ]);

    const trigger = page.locator('[data-trigger-fired="true"]');
    await expect(trigger).toBeVisible();
    await expect(trigger).toContainText('ALERT_DRAFTED');
    // The condition verbatim: a trigger nobody can read is a trigger nobody agreed to.
    await expect(trigger).toContainText('rainfall_mm_24h');
  });

  test('says nothing is forecast rather than rendering an empty table', async ({ page }) => {
    await openForecast(page, []);
    await expect(page.getByText(/no division is forecast/i)).toBeVisible();
    // And says what to do about it, rather than "no results found".
    await expect(page.getByText(/lower the class filter/i)).toBeVisible();
  });
});
