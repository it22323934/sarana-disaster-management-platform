/**
 * The provisional entitlement, computed on the device.
 *
 * A port of `ledger_svc.domain.entitlement.calculate`, step for step and string for
 * string. It exists so a GN officer sees the number while they are still standing in front
 * of the house — an obvious data-entry error caught there costs thirty seconds, and caught
 * three weeks later in a rejection it costs a household a month and a return visit that
 * may not happen.
 *
 * **This is not the authoritative calculation and the screen says so.** The server
 * recomputes on submission and its answer is the one that becomes money. What this has to
 * be is *identical*, because a provisional figure that differs from the final one is worse
 * than no figure at all: the officer tells the household 185,000 and the household receives
 * 150,000, and the officer is the one standing there when it happens.
 *
 * Identical includes the working. `data/fixtures/entitlement/cases.json` holds eighteen
 * cases across all nine categories with the traces the Python produces, and
 * `test/entitlement-parity.test.ts` asserts this module reproduces every field of every
 * one — the step descriptions, the expression strings, the cap sentences and the order
 * they appear in. A total that matched while the working differed would still fail, and
 * should: the working is what the officer reads out.
 *
 * Two things are ports rather than idioms, and both are deliberate:
 *
 *   **Integer cents throughout.** The server's money is integer cents because a float
 *   would make the hash chain depend on the platform's floating-point behaviour. JavaScript
 *   has one number type, so every arithmetic result here is floored back to an integer and
 *   `assertSafeCents` refuses anything that has left the exactly-representable range. A
 *   silent 0.999999 on a handset is a cent nobody can find later.
 *
 *   **Sorting by category before anything else.** Two identical assessments must produce
 *   the same trace whatever order the officer entered the lines in, because the trace is
 *   hashed into the ledger entry.
 */

/**
 * The nine categories the schema allows, from `ledger_svc.repo.base.DAMAGE_CATEGORIES`.
 *
 * Re-exported from the draft module rather than restated, so there is one list on the
 * device and `test/vocabulary.test.ts` holds it against the Python.
 */
export { DAMAGE_CATEGORIES, type DamageCategory } from './assessment-draft.js';

/**
 * The per-household ceiling across all categories in one event.
 *
 * `DEFAULT_HOUSEHOLD_CAP_CENTS` in the Python. Only used when a cached schedule does not
 * carry its own, which should not happen — the server sends one — but a device that fell
 * back to no ceiling would show an officer a number nobody would ever approve.
 */
export const DEFAULT_HOUSEHOLD_CAP_CENTS = 200_000_00;

/**
 * Refused, never defaulted to zero.
 *
 * The Python raises `CalculationRefused` for the same reason: a silently-zero entitlement
 * is a household that receives nothing with no reason recorded. On the device the refusal
 * reaches the officer as a sentence on the form.
 */
export class CalculationRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CalculationRefused';
  }
}

export interface ScheduleLine {
  readonly line_id: string;
  readonly category: string;
  readonly unit_amount_cents: number;
  readonly max_units: number;
  readonly formula: string;
}

export interface CostSchedule {
  readonly version: string;
  readonly lines: Readonly<Record<string, ScheduleLine>>;
  readonly household_cap_cents: number;
  /** When this copy was pulled down. Shown on the form; a stale schedule is a wrong number. */
  readonly cached_at?: string;
}

export interface AssessedItem {
  readonly category: string;
  readonly units: number;
}

export interface CalculationStep {
  readonly description: string;
  readonly expression: string;
  readonly result_cents: number;
}

export interface CalculationTrace {
  readonly cost_schedule_version: string;
  readonly formula: string;
  readonly inputs: Readonly<Record<string, number | string>>;
  readonly steps: readonly CalculationStep[];
  readonly result_lkr_cents: number;
  readonly caps_applied: readonly string[];
  readonly schedule_line_ids: readonly string[];
}

/**
 * The largest amount arithmetic here may produce before it stops being exact.
 *
 * `Number.MAX_SAFE_INTEGER` is about 9.007e15, which in cents is ninety trillion rupees —
 * far beyond any assessment. The guard is not about realistic values; it is about catching
 * a units field that has been fed a parsed `Infinity` or a hand-edited payload before the
 * number reaches a screen an officer reads out loud.
 */
const MAX_SAFE_CENTS = Number.MAX_SAFE_INTEGER;

function assertSafeCents(value: number, what: string): number {
  if (!Number.isFinite(value)) {
    throw new CalculationRefused(`${what} is not a finite amount`);
  }
  if (!Number.isSafeInteger(value)) {
    throw new CalculationRefused(
      `${what} is ${value}, which is not an exact integer number of cents. Money on this ` +
        'platform is integer cents end to end; a value that has left that range cannot be ' +
        'shown to an officer as a figure.',
    );
  }
  if (Math.abs(value) > MAX_SAFE_CENTS) {
    throw new CalculationRefused(`${what} is beyond the exactly-representable range`);
  }
  return value;
}

/** The line for a category, or a refusal naming the schedule that does not price it. */
export function lineFor(schedule: CostSchedule, category: string): ScheduleLine {
  const line = schedule.lines[category];
  if (!line) {
    throw new CalculationRefused(
      `the ${schedule.version} schedule has no line for '${category}'. An assessment ` +
        'cannot be valued against a schedule that does not price it.',
    );
  }
  return line;
}

export interface CalculateOptions {
  readonly alreadyDisbursedCents?: number;
}

/**
 * Value an assessment against a cached schedule.
 *
 * Deterministic and total: every path either produces a trace or throws. There is no
 * branch that returns a number without the working that produced it — which is the
 * property that lets the officer show the household how the figure was reached.
 */
export function calculate(
  items: readonly AssessedItem[],
  schedule: CostSchedule,
  { alreadyDisbursedCents = 0 }: CalculateOptions = {},
): CalculationTrace {
  if (alreadyDisbursedCents < 0) {
    throw new CalculationRefused('already-disbursed cannot be negative');
  }
  assertSafeCents(alreadyDisbursedCents, 'already-disbursed');

  for (const item of items) {
    if (item.units < 0) {
      throw new CalculationRefused(`${item.category}: units cannot be negative`);
    }
    if (!Number.isSafeInteger(item.units)) {
      throw new CalculationRefused(`${item.category}: units must be a whole number`);
    }
  }

  // Sorted by category, exactly as the Python sorts, so the same assessment always
  // produces the same trace whatever order the officer entered the lines in.
  const sorted = [...items].sort((a, b) => (a.category < b.category ? -1 : a.category > b.category ? 1 : 0));

  const steps: CalculationStep[] = [];
  const caps: string[] = [];
  const lineIds: string[] = [];
  const inputs: Record<string, number | string> = { cost_schedule_version: schedule.version };
  let running = 0;

  for (const item of sorted) {
    const line = lineFor(schedule, item.category);
    lineIds.push(line.line_id);

    let units = item.units;
    if (units > line.max_units) {
      caps.push(`${item.category}: units capped at ${line.max_units}`);
      units = line.max_units;
    }

    const amount = assertSafeCents(units * line.unit_amount_cents, `${item.category} amount`);
    running = assertSafeCents(running + amount, 'running total');
    // The un-capped figure, so the working shows what the officer entered as well as what
    // was allowed. `item.units`, not `units`.
    inputs[`units:${item.category}`] = item.units;

    steps.push({
      description: `${item.category} x${units}`,
      expression: `${units} * ${line.unit_amount_cents}`,
      result_cents: amount,
    });
  }

  const subtotal = running;
  steps.push({
    description: 'subtotal',
    // Built from the steps recorded so far, before the subtotal itself is pushed - the
    // Python joins over the same list at the same point. An empty assessment reads '0'.
    expression: steps.map((step) => String(step.result_cents)).join(' + ') || '0',
    result_cents: subtotal,
  });

  if (running > schedule.household_cap_cents) {
    caps.push(`household ceiling ${schedule.household_cap_cents}`);
    running = schedule.household_cap_cents;
    steps.push({
      description: 'household ceiling applied',
      expression: `min(${subtotal}, ${schedule.household_cap_cents})`,
      result_cents: running,
    });
  }

  if (alreadyDisbursedCents) {
    inputs['already_disbursed_cents'] = alreadyDisbursedCents;
    const before = running;
    // Never negative: a household that has already received more than the schedule allows
    // is owed nothing further, not asked for money back by an arithmetic accident.
    running = Math.max(0, before - alreadyDisbursedCents);
    steps.push({
      description: 'less already disbursed',
      expression: `max(0, ${before} - ${alreadyDisbursedCents})`,
      result_cents: running,
    });
  }

  return {
    cost_schedule_version: schedule.version,
    formula: sorted.map((item) => lineFor(schedule, item.category).formula).join(' + ') || '0',
    inputs,
    steps,
    result_lkr_cents: running,
    caps_applied: caps,
    schedule_line_ids: lineIds,
  };
}

/**
 * The working in one line, for the form's summary row.
 *
 * `as_sentence` in the Python. The device renders the steps as a list too, but this is
 * what goes into the one-line preview and into an SMS if one is ever sent from here.
 */
export function asSentence(trace: CalculationTrace): string {
  const parts = trace.steps.map(
    (step) => `${step.description}: ${(step.result_cents / 100).toLocaleString('en-LK', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`,
  );
  const caps = trace.caps_applied.length > 0 ? ` (capped: ${trace.caps_applied.join(', ')})` : '';
  return parts.join('; ') + caps;
}

/**
 * Build a schedule from what the server publishes at `GET /api/v1/cost-schedules`.
 *
 * The public endpoint's shape is not the calculator's: it sends `rate_lkr_cents` and
 * `cap_lkr_cents` per line and no unit ceiling, because it is describing the schedule to a
 * reader rather than feeding an arithmetic. The mapping is here, in one place, so a change
 * at that boundary is one edit rather than nine.
 *
 * A line whose single unit already exceeds the household ceiling is refused, matching
 * `CostSchedule.__post_init__`: it can never be paid in full, and discovering that one
 * household at a time is the expensive way to find a misconfigured schedule.
 */
export function scheduleFromPublished(
  published: {
    readonly version: string;
    readonly household_cap_cents?: number | null;
    readonly lines: readonly {
      readonly id: string;
      readonly category: string;
      readonly rate_lkr_cents: number;
      readonly cap_lkr_cents?: number | null;
      readonly formula?: Readonly<Record<string, unknown>> | string | null;
    }[];
  },
  { cachedAt }: { cachedAt?: string } = {},
): CostSchedule {
  const householdCap = published.household_cap_cents ?? DEFAULT_HOUSEHOLD_CAP_CENTS;
  const lines: Record<string, ScheduleLine> = {};

  for (const line of published.lines) {
    if (line.rate_lkr_cents < 0) {
      throw new CalculationRefused('a schedule line cannot carry a negative amount');
    }
    if (line.rate_lkr_cents > householdCap) {
      throw new CalculationRefused(
        `schedule ${published.version}: ${line.category} is priced at ${line.rate_lkr_cents} ` +
          `but the household ceiling is ${householdCap}, so this category can never be paid ` +
          'in full. Raise the ceiling or reprice the line.',
      );
    }

    lines[line.category] = {
      line_id: line.id,
      category: line.category,
      unit_amount_cents: line.rate_lkr_cents,
      // The per-line ceiling divided by the rate is how many units the schedule will pay
      // for. No cap means one unit: a category the schedule does not bound is not a
      // category an officer may claim ten of.
      max_units:
        line.cap_lkr_cents && line.rate_lkr_cents > 0
          ? Math.max(1, Math.floor(line.cap_lkr_cents / line.rate_lkr_cents))
          : 1,
      formula:
        typeof line.formula === 'string'
          ? line.formula
          : ((line.formula?.['expression'] as string | undefined) ?? `${line.category.toLowerCase()} * rate`),
    };
  }

  return {
    version: published.version,
    lines,
    household_cap_cents: householdCap,
    ...(cachedAt ? { cached_at: cachedAt } : {}),
  };
}
