/**
 * The entitlement calculation, rendered for the person it is about.
 *
 * The ops console shows the same trace to an officer who knows what a schedule version is.
 * This shows it to a household, and the difference is not simplification - it is that
 * every number in it has to be checkable. The household should be able to read the rate
 * here, open the published schedule, and find the same figure.
 *
 * The trace comes from `ledger_svc.domain.entitlement.CalculationTrace` and is not
 * reinterpreted: the steps are rendered in the order they were applied, with the same
 * expressions and the same results. A UI that recomputed the total would be a second
 * implementation of the thing the trace exists to make unnecessary.
 */

import { formatLKR } from '@sarana/ts-shared/format';

/** One step of the working, as `CalculationStep.as_dict` writes it. */
export interface TraceStep {
  readonly description: string;
  readonly expression: string;
  readonly result_cents: number;
}

/** `CalculationTrace.as_dict`. */
export interface CalculationTrace {
  readonly cost_schedule_version: string;
  readonly formula: string;
  readonly inputs: Readonly<Record<string, number | string>>;
  readonly steps: readonly TraceStep[];
  readonly result_lkr_cents: number;
  readonly caps_applied: readonly string[];
  readonly schedule_line_ids: readonly string[];
}

export interface ExplanationLine {
  /**
   * The i18n key for the sentence, or null when the line is a step from the server.
   *
   * A step's `description` is written by the calculator in English and is not translated -
   * it is data, not copy. Rendering it verbatim would put an English sentence in a Tamil
   * screen, so the app pairs each step with a key and shows the expression and the money,
   * which are the parts a household actually checks.
   */
  readonly messageKey: string;
  readonly values: Readonly<Record<string, string | number>>;
  /** The arithmetic, shown as written. `250000 * 0.6`, not prose. */
  readonly expression: string | null;
  /**
   * The result of this line, formatted.
   *
   * `formatLKR` groups in `en-LK` in every language on purpose: Tamil groups in lakhs and
   * crores, so the same entitlement would read `LKR 1,25,000.00` to one household member
   * and `LKR 125,000.00` to another off the same screen.
   */
  readonly amount: string | null;
}

export interface Explanation {
  readonly lines: readonly ExplanationLine[];
  readonly total: string;
  readonly totalCents: number;
  /** The version the household can look up. Shown, not hidden behind a link. */
  readonly scheduleVersion: string;
  readonly capApplied: boolean;
}

/**
 * Turn a trace into something a non-specialist reads top to bottom.
 *
 * `caps_applied` gets its own line whether or not a cap bound, because "no cap was
 * applied" is information: a household that has heard a ceiling exists needs to be told
 * it did not bite, or they will assume it did and that the figure was reduced.
 */
export function explain(trace: CalculationTrace): Explanation {
  const lines: ExplanationLine[] = [
    {
      messageKey: 'aid.explain.schedule',
      values: { version: trace.cost_schedule_version },
      expression: null,
      amount: null,
    },
  ];

  for (const step of trace.steps) {
    lines.push({
      messageKey: 'aid.explain.step',
      values: { description: step.description },
      expression: step.expression,
      amount: formatLKR(step.result_cents),
    });
  }

  lines.push(
    trace.caps_applied.length > 0
      ? {
          messageKey: 'aid.explain.capped',
          values: { caps: trace.caps_applied.join(', ') },
          expression: null,
          amount: null,
        }
      : {
          messageKey: 'aid.explain.notCapped',
          values: {},
          expression: null,
          amount: null,
        },
  );

  return {
    lines,
    total: formatLKR(trace.result_lkr_cents),
    totalCents: trace.result_lkr_cents,
    scheduleVersion: trace.cost_schedule_version,
    capApplied: trace.caps_applied.length > 0,
  };
}

/**
 * Whether the trace is complete enough to show at all.
 *
 * An entitlement with no steps is one the calculator never ran on, and rendering "Total:
 * Rs. 150,000" with no working under it is exactly the opacity this screen exists to
 * remove. The screen shows the amount and says the working is unavailable, which is a
 * thing a household can raise a grievance about.
 */
export function isExplainable(trace: CalculationTrace | null | undefined): trace is CalculationTrace {
  return (
    trace !== null &&
    trace !== undefined &&
    Array.isArray(trace.steps) &&
    trace.steps.length > 0 &&
    typeof trace.result_lkr_cents === 'number'
  );
}
