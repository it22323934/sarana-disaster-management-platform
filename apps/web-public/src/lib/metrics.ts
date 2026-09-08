/**
 * The metrics the district table and the choropleth can be read by.
 *
 * One list, shared by both. The table and the map colour by the same definition or they
 * are two different claims sitting beside each other on the same page, and the map is the
 * one people screenshot.
 *
 * **`higherIsBetter` exists so the choropleth cannot lie by ramp direction.** Disbursed
 * money reads well when it is high; median days to disbursement reads well when it is low.
 * A single ramp applied to both would paint the slowest district in the same colour as the
 * best-funded one, and a reader who has learned that dark means good would draw exactly
 * the wrong conclusion from the page the brief calls the most newsworthy view on the site.
 */

import type { DistrictMetrics } from './public-api';

export type MetricId =
  | 'assessed'
  | 'approved'
  | 'disbursed'
  | 'perHousehold'
  | 'confirmationRate'
  | 'medianDays'
  | 'grievanceRate';

export interface MetricDefinition {
  readonly id: MetricId;
  /** Message key under the `districts` namespace. */
  readonly labelKey: string;
  /** The raw value, or null where the district has no basis for the figure. */
  readonly value: (row: DistrictMetrics) => number | null;
  /** How the value is rendered in a cell. Formatting stays at the render boundary. */
  readonly kind: 'money' | 'percent' | 'days' | 'rate';
  readonly higherIsBetter: boolean;
}

export const METRICS: readonly MetricDefinition[] = [
  {
    id: 'assessed',
    labelKey: 'metricAssessed',
    value: (row) => row.assessed_lkr_cents,
    kind: 'money',
    higherIsBetter: true,
  },
  {
    id: 'approved',
    labelKey: 'metricApproved',
    value: (row) => row.approved_lkr_cents,
    kind: 'money',
    higherIsBetter: true,
  },
  {
    id: 'disbursed',
    labelKey: 'metricDisbursed',
    value: (row) => row.disbursed_lkr_cents,
    kind: 'money',
    higherIsBetter: true,
  },
  {
    id: 'perHousehold',
    labelKey: 'metricPerHousehold',
    value: (row) => row.disbursed_per_household_lkr_cents,
    kind: 'money',
    higherIsBetter: true,
  },
  {
    id: 'confirmationRate',
    labelKey: 'metricConfirmationRate',
    value: (row) => row.confirmation_rate,
    kind: 'percent',
    higherIsBetter: true,
  },
  {
    id: 'medianDays',
    labelKey: 'metricMedianDays',
    value: (row) => row.median_days_to_disbursement,
    kind: 'days',
    // The "where is it slow" view. Fewer days is better, so the ramp runs the other way.
    higherIsBetter: false,
  },
  {
    id: 'grievanceRate',
    labelKey: 'metricGrievanceRate',
    value: (row) => row.grievance_rate_per_1000_disbursements,
    kind: 'rate',
    higherIsBetter: false,
  },
] as const;

export const DEFAULT_METRIC: MetricId = 'disbursed';

export function metricById(id: string | undefined): MetricDefinition {
  return METRICS.find((metric) => metric.id === id) ?? METRICS.find((m) => m.id === DEFAULT_METRIC)!;
}

/**
 * Where a value sits between the lowest and highest districts, as 0 to 1.
 *
 * Null in, null out. A district with no basis for a metric is not at the bottom of the
 * scale — it is off the scale, and the map renders it in a distinct "no data" fill rather
 * than the palest end of the ramp. The two look similar and mean opposite things: pale
 * usually reads as "almost none", and "we do not know" is not "almost none".
 *
 * The direction is applied here rather than in the colour function, so the table's sort
 * and the map's fill cannot disagree about which end is good.
 */
export function normalise(
  value: number | null,
  rows: readonly DistrictMetrics[],
  metric: MetricDefinition,
): number | null {
  if (value === null) return null;

  const values = rows
    .map((row) => metric.value(row))
    .filter((candidate): candidate is number => candidate !== null);
  if (values.length === 0) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  // Every district equal is a real outcome, not a divide-by-zero. Mid-scale is the honest
  // rendering: nothing here is better or worse than anything else.
  if (max === min) return 0.5;

  const position = (value - min) / (max - min);
  return metric.higherIsBetter ? position : 1 - position;
}
