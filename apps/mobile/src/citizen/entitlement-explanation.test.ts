/**
 * The entitlement calculation, as a household reads it.
 *
 * The property being protected: **the app never recomputes the total.** Every figure
 * shown comes out of the trace the ledger wrote, so a household reading this screen and an
 * auditor reading the ledger are reading the same arithmetic.
 */

import { describe, expect, it } from 'vitest';

import { explain, isExplainable, type CalculationTrace } from './entitlement-explanation.js';

/** The example from file 23, as `CalculationTrace.as_dict` would write it. */
const PARTIAL_HOUSE: CalculationTrace = {
  cost_schedule_version: '2026.1',
  formula: 'sum(unit_amount * units) capped at household_cap',
  inputs: { category: 'HOUSE_PARTIAL', units: 1, unit_amount_cents: 25_000_000 },
  steps: [
    {
      description: 'HOUSE_PARTIAL: 1 x 250000.00',
      expression: '25000000 * 1',
      result_cents: 25_000_000,
    },
  ],
  result_lkr_cents: 25_000_000,
  caps_applied: [],
  schedule_line_ids: ['2026.1/HOUSE_PARTIAL'],
};

const CAPPED: CalculationTrace = {
  ...PARTIAL_HOUSE,
  steps: [
    { description: 'HOUSE_FULL: 1 x 500000.00', expression: '50000000 * 1', result_cents: 50_000_000 },
    { description: 'household cap', expression: 'min(50000000, 40000000)', result_cents: 40_000_000 },
  ],
  result_lkr_cents: 40_000_000,
  caps_applied: ['household_cap'],
};

describe('explain', () => {
  it('opens with the schedule version, so the household can look up the rate', () => {
    const explanation = explain(PARTIAL_HOUSE);
    expect(explanation.lines[0]).toMatchObject({
      messageKey: 'aid.explain.schedule',
      values: { version: '2026.1' },
    });
    expect(explanation.scheduleVersion).toBe('2026.1');
  });

  it('renders one line per step, in the order they were applied', () => {
    const explanation = explain(CAPPED);
    const steps = explanation.lines.filter((line) => line.messageKey === 'aid.explain.step');
    expect(steps).toHaveLength(2);
    expect(steps[0]?.expression).toBe('50000000 * 1');
    expect(steps[1]?.expression).toBe('min(50000000, 40000000)');
  });

  it('shows the arithmetic as the ledger wrote it, not as prose', () => {
    // A household checking a figure needs the expression, not a paraphrase of it.
    expect(explain(PARTIAL_HOUSE).lines[1]?.expression).toBe('25000000 * 1');
  });

  it('takes the total from the trace rather than adding the steps up', () => {
    // Recomputing would be a second implementation of the thing the trace exists to make
    // unnecessary - and the one that disagreed would be this one.
    expect(explain(CAPPED).totalCents).toBe(40_000_000);
    expect(explain(CAPPED).total).toBe('LKR 400,000.00');
  });

  it('says a cap was applied, and names it', () => {
    const explanation = explain(CAPPED);
    expect(explanation.capApplied).toBe(true);
    expect(explanation.lines.at(-1)).toMatchObject({
      messageKey: 'aid.explain.capped',
      values: { caps: 'household_cap' },
    });
  });

  it('says when no cap was applied, because silence would be read as one', () => {
    // A household that has heard a ceiling exists will assume it bit and that the figure
    // was reduced, unless told otherwise.
    const explanation = explain(PARTIAL_HOUSE);
    expect(explanation.capApplied).toBe(false);
    expect(explanation.lines.at(-1)?.messageKey).toBe('aid.explain.notCapped');
  });

  it('groups money the same way for every reader', () => {
    // Tamil groups in lakhs and crores. Two people reading one figure off one screen and
    // saying different numbers aloud is the failure `formatLKR` pins `en-LK` to prevent.
    expect(explain(PARTIAL_HOUSE).total).toBe('LKR 250,000.00');
  });
});

describe('isExplainable', () => {
  it('refuses a trace with no working', () => {
    // An entitlement the calculator never ran on. Rendering "Total: Rs. 150,000" with
    // nothing under it is exactly the opacity this screen exists to remove.
    expect(isExplainable({ ...PARTIAL_HOUSE, steps: [] })).toBe(false);
    expect(isExplainable(null)).toBe(false);
    expect(isExplainable(undefined)).toBe(false);
  });

  it('accepts a complete one', () => {
    expect(isExplainable(PARTIAL_HOUSE)).toBe(true);
  });
});
