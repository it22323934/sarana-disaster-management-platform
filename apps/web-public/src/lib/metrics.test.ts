/**
 * The choropleth cannot lie by ramp direction, and "no data" is not "the best value".
 *
 * Two failures are being prevented here and both are about what a map asserts.
 *
 * **Direction.** Disbursed money reads well when it is high; median days to disbursement
 * reads well when it is low. One ramp over both would paint the slowest district the same
 * colour as the best-funded one, and a reader who has learned that dark means good would
 * draw exactly the wrong conclusion from the page the brief calls the most newsworthy view
 * on the site.
 *
 * **Absence.** A district with no basis for a metric is off the scale, not at the bottom of
 * it. Pale reads as "almost none"; "we do not know" is not "almost none".
 */

import { describe, expect, it } from 'vitest';

import { DEFAULT_METRIC, METRICS, metricById, normalise } from './metrics';
import type { DistrictMetrics } from './public-api';

function district(overrides: Partial<DistrictMetrics>): DistrictMetrics {
  return {
    district_code: 'LK-00',
    assessed_count: 0,
    assessed_households: 0,
    assessed_divisions: 0,
    assessed_lkr_cents: 0,
    approved_count: 0,
    approved_lkr_cents: 0,
    disbursed_count: 0,
    disbursed_lkr_cents: 0,
    confirmed_count: 0,
    reversed_count: 0,
    confirmation_rate: null,
    median_days_to_disbursement: null,
    disbursed_per_household_lkr_cents: null,
    grievance_count: 0,
    grievance_open_count: 0,
    grievance_rate_per_1000_disbursements: null,
    median_grievance_resolution_days: null,
    last_released_at: null,
    ...overrides,
  };
}

describe('metric selection', () => {
  it('falls back to the default rather than throwing on an unknown id', () => {
    // The metric comes from a query string a reader can edit. A junk value must render the
    // default view, not a 500.
    expect(metricById('nonsense').id).toBe(DEFAULT_METRIC);
    expect(metricById(undefined).id).toBe(DEFAULT_METRIC);
  });

  it('every metric declares a direction', () => {
    // Not a tidiness check. A metric added without one would default to `undefined`, which
    // is falsy, and would silently be treated as lower-is-better.
    for (const metric of METRICS) {
      expect(typeof metric.higherIsBetter).toBe('boolean');
    }
  });
});

describe('normalise applies the metric direction', () => {
  const rows = [
    district({ district_code: 'LK-01', disbursed_lkr_cents: 100, median_days_to_disbursement: 5 }),
    district({ district_code: 'LK-02', disbursed_lkr_cents: 900, median_days_to_disbursement: 45 }),
  ];

  it('puts the largest disbursement at the strong end', () => {
    const money = metricById('disbursed');
    expect(normalise(900, rows, money)).toBe(1);
    expect(normalise(100, rows, money)).toBe(0);
  });

  it('puts the fastest district at the strong end, not the slowest', () => {
    const days = metricById('medianDays');
    // Five days is good. Without the direction flip this would be 0 — the same colour as
    // the district that took forty-five.
    expect(normalise(5, rows, days)).toBe(1);
    expect(normalise(45, rows, days)).toBe(0);
  });

  it('returns null for a district with no basis for the metric', () => {
    const days = metricById('medianDays');
    expect(normalise(null, rows, days)).toBeNull();
  });

  it('returns null when no district has a value, rather than dividing by nothing', () => {
    const days = metricById('medianDays');
    const empty = [district({}), district({})];
    expect(normalise(null, empty, days)).toBeNull();
  });

  it('puts every district mid-scale when they are all equal', () => {
    // A real outcome, not a divide-by-zero. Mid-scale says nothing here is better or worse
    // than anything else, which is what the data says.
    const money = metricById('disbursed');
    const flat = [
      district({ disbursed_lkr_cents: 500 }),
      district({ disbursed_lkr_cents: 500 }),
    ];
    expect(normalise(500, flat, money)).toBe(0.5);
  });
});

describe('the "where is it slow" view is reachable', () => {
  it('median days to disbursement is a selectable metric and is lower-is-better', () => {
    const metric = METRICS.find((candidate) => candidate.id === 'medianDays');
    expect(metric).toBeDefined();
    expect(metric?.higherIsBetter).toBe(false);
    expect(metric?.kind).toBe('days');
  });

  it('the grievance rate is also lower-is-better', () => {
    expect(METRICS.find((m) => m.id === 'grievanceRate')?.higherIsBetter).toBe(false);
  });
});
