/**
 * The device and the server compute the same entitlement.
 * `pnpm --filter mobile test -- entitlement-parity`
 *
 * File 24's third Definition-of-Done command, and the one with a person on the other end
 * of it. The Field Companion shows a provisional figure while the officer is still
 * standing in front of the house. The server recomputes on submission and its answer
 * becomes the money. If the two differ, the officer told the household a number the
 * household will not receive — and the officer is the one who has to go back and explain.
 *
 * `data/fixtures/entitlement/cases.json` is generated from
 * `ledger_svc.domain.entitlement.calculate` by `tools/fixtures/entitlement_cases.py`, and
 * `tests/ledger/test_entitlement_fixtures.py` asserts the Python still produces it. This
 * file asserts the TypeScript produces it too. One fixture, two implementations, and the
 * fixture is the contract between them.
 *
 * **Every field of the trace is compared, not just the total.** A total that matched while
 * the working differed would still be a failure: the working is what the officer reads out
 * to the household, and it is what gets hashed into the ledger entry. A step description
 * that drifted would show up as two different explanations of the same payment.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  CalculationRefused,
  calculate,
  scheduleFromPublished,
  type AssessedItem,
  type CalculationTrace,
  type CostSchedule,
  type ScheduleLine,
} from '../src/field/entitlement.js';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const FIXTURE = join(REPO_ROOT, 'data', 'fixtures', 'entitlement', 'cases.json');

interface Fixture {
  readonly schedule: {
    readonly version: string;
    readonly household_cap_cents: number;
    readonly lines: readonly ScheduleLine[];
  };
  readonly cases: readonly {
    readonly name: string;
    readonly why: string;
    readonly items: readonly AssessedItem[];
    readonly already_disbursed_cents: number;
    readonly expected: CalculationTrace;
  }[];
}

const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8')) as Fixture;

const schedule: CostSchedule = {
  version: fixture.schedule.version,
  household_cap_cents: fixture.schedule.household_cap_cents,
  lines: Object.fromEntries(fixture.schedule.lines.map((line) => [line.category, line])),
};

describe('the fixture is worth reading', () => {
  it('covers every damage category the schema allows', () => {
    // Guards the guard: a fixture that lost a category would pass every case below while
    // testing eight ninths of the calculator. The brief asks for parity across all
    // categories, so the count is asserted rather than assumed.
    expect(fixture.schedule.lines).toHaveLength(9);
    const singles = fixture.cases.filter((entry) => entry.name.startsWith('single-'));
    expect(singles).toHaveLength(9);
  });

  it('exercises both caps and the deduction', () => {
    const names = fixture.cases.map((entry) => entry.name);
    expect(names).toContain('units-capped');
    expect(names).toContain('household-ceiling');
    expect(names).toContain('already-disbursed');
    expect(names).toContain('already-disbursed-exceeds');
    expect(names).toContain('ceiling-then-disbursed');
  });
});

describe.each(fixture.cases)('$name', (entry) => {
  const actual = () =>
    calculate(entry.items, schedule, { alreadyDisbursedCents: entry.already_disbursed_cents });

  it(`produces the server's total — ${entry.why}`, () => {
    expect(actual().result_lkr_cents).toBe(entry.expected.result_lkr_cents);
  });

  it("produces the server's working, step for step and string for string", () => {
    // Deep equality on the steps rather than a length check. The description and the
    // expression are what the officer reads; a step whose numbers agreed but whose
    // sentence differed would be two explanations of one payment.
    expect(actual().steps).toEqual(entry.expected.steps);
  });

  it("produces the server's caps, in the same order", () => {
    expect(actual().caps_applied).toEqual(entry.expected.caps_applied);
  });

  it("produces the server's inputs, formula and line ids", () => {
    const trace = actual();
    expect(trace.inputs).toEqual(entry.expected.inputs);
    expect(trace.formula).toBe(entry.expected.formula);
    expect(trace.schedule_line_ids).toEqual(entry.expected.schedule_line_ids);
    expect(trace.cost_schedule_version).toBe(entry.expected.cost_schedule_version);
  });

  it('is byte-identical to the server trace when serialised', () => {
    // The strongest form of the assertion, and the one that catches a field this port
    // forgot to emit at all: an extra or missing key changes the JSON even when every
    // key both sides have agrees.
    expect(JSON.parse(JSON.stringify(actual()))).toEqual(entry.expected);
  });
});

describe('every category is priced identically to the server', () => {
  // A second pass over the same ground, framed as the brief frames it: "for every
  // category". A failure here names the category rather than a case number.
  for (const line of fixture.schedule.lines) {
    it(`${line.category} at one unit`, () => {
      const expected = fixture.cases.find((entry) => entry.name === `single-${line.category.toLowerCase()}`);
      expect(expected, `no fixture case for ${line.category}`).toBeDefined();
      expect(calculate([{ category: line.category, units: 1 }], schedule).result_lkr_cents).toBe(
        expected!.expected.result_lkr_cents,
      );
    });
  }
});

describe('the device refuses what the server refuses', () => {
  it('refuses a category the cached schedule does not price', () => {
    // The server raises `CalculationRefused` with the same reasoning. On the device this
    // reaches the officer as a sentence on the form rather than a silent zero, which is
    // the whole point: a zero entitlement with no reason is a household that receives
    // nothing and cannot ask why.
    expect(() => calculate([{ category: 'NOT_A_CATEGORY', units: 1 }], schedule)).toThrow(
      CalculationRefused,
    );
  });

  it('refuses negative units', () => {
    expect(() => calculate([{ category: 'CROP', units: -1 }], schedule)).toThrow(
      CalculationRefused,
    );
  });

  it('refuses a negative already-disbursed', () => {
    expect(() => calculate([], schedule, { alreadyDisbursedCents: -1 })).toThrow(
      CalculationRefused,
    );
  });

  it('refuses units that are not whole numbers', () => {
    // JavaScript has one number type and a text input produces strings. A parsed `2.5`
    // reaching the calculator would produce a fractional cent, which is exactly the class
    // of bug integer cents exist to prevent.
    expect(() => calculate([{ category: 'CROP', units: 2.5 }], schedule)).toThrow(
      CalculationRefused,
    );
  });

  it('refuses an already-disbursed amount outside the exact integer range', () => {
    // The reachable overflow path, and the only one.
    //
    // A huge *units* value cannot overflow: the unit ceiling is applied before the
    // multiplication, so the amount is bounded by `max_units * unit_amount_cents` whatever
    // the officer types. The deduction has no such ceiling — it arrives from the server as
    // a figure about this household — so it is where an unsafe number can actually reach
    // the arithmetic.
    expect(() =>
      calculate([{ category: 'CROP', units: 1 }], schedule, {
        alreadyDisbursedCents: Number.MAX_SAFE_INTEGER + 2,
      }),
    ).toThrow(CalculationRefused);
  });

  it('caps absurd units rather than overflowing on them', () => {
    // The other half of the same statement, asserted rather than left implied: a units
    // field fed a nonsense value produces the capped figure and names the cap, which is
    // what an officer can act on. Refusing outright would lose the rest of the assessment.
    const trace = calculate([{ category: 'CROP', units: Number.MAX_SAFE_INTEGER }], schedule);
    expect(trace.result_lkr_cents).toBe(5 * 15_000_00);
    expect(trace.caps_applied).toEqual(['CROP: units capped at 5']);
  });
});

describe('scheduleFromPublished', () => {
  const published = {
    version: '2026-03',
    household_cap_cents: 400_000_00,
    lines: [
      {
        id: 'line-1',
        category: 'HOUSE_FULL',
        rate_lkr_cents: 250_000_00,
        cap_lkr_cents: 250_000_00,
        formula: { expression: 'house_full * 250000' },
      },
      {
        id: 'line-2',
        category: 'CROP',
        rate_lkr_cents: 15_000_00,
        cap_lkr_cents: 75_000_00,
        formula: { expression: 'crop_acres * 15000' },
      },
    ],
  };

  it('derives the unit ceiling from the per-line cap', () => {
    const built = scheduleFromPublished(published);
    expect(built.lines['CROP']?.max_units).toBe(5);
    expect(built.lines['HOUSE_FULL']?.max_units).toBe(1);
  });

  it('defaults an uncapped line to one unit rather than to unlimited', () => {
    // A category the schedule does not bound is not a category an officer may claim ten
    // of. Defaulting the other way would let a mis-typed units field produce a figure
    // nobody would approve, on a screen that says "provisional".
    const built = scheduleFromPublished({
      ...published,
      lines: [{ id: 'line-3', category: 'INJURY', rate_lkr_cents: 20_000_00 }],
    });
    expect(built.lines['INJURY']?.max_units).toBe(1);
  });

  it('refuses a line priced above the household ceiling, as the server does', () => {
    // `CostSchedule.__post_init__` raises here too. Such a line can never be paid in full,
    // and finding that out one household at a time is the expensive way to discover a
    // misconfigured schedule.
    expect(() =>
      scheduleFromPublished({
        version: 'bad',
        household_cap_cents: 100_000_00,
        lines: [{ id: 'line-4', category: 'HOUSE_FULL', rate_lkr_cents: 250_000_00 }],
      }),
    ).toThrow(CalculationRefused);
  });

  it('falls back to the documented household ceiling when the server sends none', () => {
    const built = scheduleFromPublished({ version: 'v', lines: [] });
    expect(built.household_cap_cents).toBe(200_000_00);
  });
});
