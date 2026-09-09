/**
 * What the form refuses on the device, and the reason it gives.
 *
 * Every case here is one the brief names or one the officer will actually hit. Two
 * properties are asserted throughout and both matter more than the boolean:
 *
 *   **The refusal names the bound.** "Invalid value" sends an officer through nine fields;
 *   "the schedule pays for at most 5, you entered 9" tells them what to change. A validator
 *   that cannot explain itself gets worked around, and a worked-around validator is worse
 *   than none because it looks like a control.
 *
 *   **Advisory is not blocking.** A stale schedule is worth saying and must not stop an
 *   officer working. Getting that the wrong way round would strand a whole division's
 *   assessments behind a warning nobody in the field can clear.
 */

import { describe, expect, it } from 'vitest';

import type { CostSchedule } from './entitlement.js';
import {
  GPS_ACCURACY_THRESHOLD_M,
  MINIMUM_PHOTOS,
  SCHEDULE_STALE_AFTER_DAYS,
  maySave,
  staleScheduleProblem,
  validateAssessment,
  validateItem,
  type AssessmentFormState,
} from './validation.js';

const NOW = Date.UTC(2026, 8, 8, 6, 0, 0);

const SCHEDULE: CostSchedule = {
  version: '2026-03',
  household_cap_cents: 400_000_00,
  cached_at: new Date(NOW - 2 * 86_400_000).toISOString(),
  lines: {
    CROP: {
      line_id: 'line-crop',
      category: 'CROP',
      unit_amount_cents: 15_000_00,
      max_units: 5,
      formula: 'crop * 15000',
    },
    HOUSE_FULL: {
      line_id: 'line-hf',
      category: 'HOUSE_FULL',
      unit_amount_cents: 250_000_00,
      max_units: 1,
      formula: 'house_full * 250000',
    },
  },
};

const VALID: AssessmentFormState = {
  householdLocalId: 'hh_local_1',
  items: [{ category: 'CROP', units: 2 }],
  photoCount: 2,
  latitude: 7.2906,
  longitude: 80.6337,
  gpsAccuracyM: 12,
  locationSource: 'GPS',
};

const CONTEXT = { schedule: SCHEDULE, now: NOW, division: 'LK-2-05-020-1015' };

const blocking = (problems: ReturnType<typeof validateAssessment>) =>
  problems.filter((problem) => problem.severity === 'blocking');

describe('a complete assessment is accepted', () => {
  it('has nothing blocking it', () => {
    expect(blocking(validateAssessment(VALID, CONTEXT))).toEqual([]);
    expect(maySave(validateAssessment(VALID, CONTEXT))).toBe(true);
  });
});

describe('an out-of-bounds cost value is rejected on device before save', () => {
  // The brief's third test case, and the one with the clearest cost: caught in the field
  // it is thirty seconds, caught three weeks later it is work that cannot be redone
  // because the debris has been cleared.
  it('refuses units above the schedule ceiling and names the ceiling', () => {
    const problems = validateItem({ category: 'CROP', units: 9 }, 0, SCHEDULE);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.severity).toBe('blocking');
    expect(problems[0]?.message).toContain('at most 5');
    expect(problems[0]?.message).toContain('You entered 9');
  });

  it('stops the whole form, not just the row', () => {
    const problems = validateAssessment(
      { ...VALID, items: [{ category: 'CROP', units: 9 }] },
      CONTEXT,
    );
    expect(maySave(problems)).toBe(false);
  });

  it('refuses a fractional quantity', () => {
    // A text input produces strings, and a parsed `2.5` reaching the calculator produces
    // a fractional cent - the class of bug integer money exists to prevent.
    const problems = validateItem({ category: 'CROP', units: 2.5 }, 0, SCHEDULE);
    expect(problems[0]?.message).toContain('whole number');
  });

  it('refuses a negative quantity', () => {
    expect(validateItem({ category: 'CROP', units: -1 }, 0, SCHEDULE)[0]?.severity).toBe(
      'blocking',
    );
  });

  it('refuses a category the platform does not record, without mentioning units', () => {
    // Ordering matters: a units message about a category the schedule cannot price would
    // answer the wrong question and send the officer to the wrong field.
    const problems = validateItem({ category: 'NOT_REAL', units: 99 }, 0, SCHEDULE);
    expect(problems).toHaveLength(1);
    expect(problems[0]?.field).toBe('items[0].category');
  });

  it('refuses a real category the cached schedule does not price, and says what to do', () => {
    // Different from an unknown category: this one is valid and the device's copy of the
    // schedule is too old or too narrow to value it. The officer can sync or use paper.
    const problems = validateItem({ category: 'LIVESTOCK', units: 1 }, 0, SCHEDULE);
    expect(problems[0]?.message).toContain('does not price LIVESTOCK');
    expect(problems[0]?.message).toContain('paper form');
  });
});

describe('evidence', () => {
  it('requires two photographs and says why', () => {
    const problems = blocking(validateAssessment({ ...VALID, photoCount: 1 }, CONTEXT));
    expect(problems.some((problem) => problem.field === 'photos')).toBe(true);
    expect(problems.find((problem) => problem.field === 'photos')?.message).toContain('audit');
  });

  it(`accepts exactly ${MINIMUM_PHOTOS}`, () => {
    expect(blocking(validateAssessment({ ...VALID, photoCount: MINIMUM_PHOTOS }, CONTEXT))).toEqual(
      [],
    );
  });
});

describe('location', () => {
  it('refuses a GPS fix too coarse to tell one house from its neighbour', () => {
    const problems = blocking(
      validateAssessment({ ...VALID, gpsAccuracyM: GPS_ACCURACY_THRESHOLD_M + 1 }, CONTEXT),
    );
    const location = problems.find((problem) => problem.field === 'location');
    expect(location?.message).toContain(`${GPS_ACCURACY_THRESHOLD_M}m`);
  });

  it('accepts a hand-placed pin at any accuracy', () => {
    // The officer standing at the house knows better than a receiver under a wet canopy.
    // Which one produced the coordinate is recorded; neither is refused.
    expect(
      blocking(
        validateAssessment(
          { ...VALID, locationSource: 'MANUAL', gpsAccuracyM: null },
          CONTEXT,
        ),
      ),
    ).toEqual([]);
  });

  it('refuses no location at all', () => {
    const problems = blocking(
      validateAssessment({ ...VALID, latitude: null, longitude: null }, CONTEXT),
    );
    expect(problems.some((problem) => problem.field === 'location')).toBe(true);
  });

  it('accepts a fix exactly at the threshold', () => {
    // The boundary is inclusive on the good side. An off-by-one here refuses a fix the
    // policy allows, which trains officers to place pins by hand out of habit.
    expect(
      blocking(validateAssessment({ ...VALID, gpsAccuracyM: GPS_ACCURACY_THRESHOLD_M }, CONTEXT)),
    ).toEqual([]);
  });
});

describe('the household must be inside the permit', () => {
  it('refuses a household in another division, before the officer types', () => {
    // The capability token is pinned to one division. Caught here it costs nothing;
    // caught on sync it is a refusal three days later, in a division the officer has left.
    const problems = blocking(
      validateAssessment(VALID, { ...CONTEXT, householdDivision: 'LK-2-05-021-1016' }),
    );
    const household = problems.find((problem) => problem.field === 'household');
    expect(household?.message).toContain('LK-2-05-021-1016');
    expect(household?.message).toContain('refused when it syncs');
  });

  it('refuses a form with no household selected', () => {
    expect(
      blocking(validateAssessment({ ...VALID, householdLocalId: null }, CONTEXT)).some(
        (problem) => problem.field === 'household',
      ),
    ).toBe(true);
  });

  it('refuses a form with no damage recorded', () => {
    expect(
      blocking(validateAssessment({ ...VALID, items: [] }, CONTEXT)).some(
        (problem) => problem.field === 'items',
      ),
    ).toBe(true);
  });
});

describe('a stale schedule is said, not enforced', () => {
  const stale = {
    ...SCHEDULE,
    cached_at: new Date(NOW - (SCHEDULE_STALE_AFTER_DAYS + 3) * 86_400_000).toISOString(),
  };

  it('warns once the copy is old enough to matter', () => {
    const problem = staleScheduleProblem(stale, NOW);
    expect(problem?.severity).toBe('advisory');
    expect(problem?.message).toContain('17 days old');
  });

  it('does not stop the officer working', () => {
    // The case that decides whether a cut-off division gets assessed at all. An officer
    // three weeks from a signal is working from the newest schedule that exists on their
    // handset, and that is the right thing to do.
    const problems = validateAssessment(VALID, { ...CONTEXT, schedule: stale });
    expect(maySave(problems)).toBe(true);
    expect(problems.some((problem) => problem.field === 'schedule')).toBe(true);
  });

  it('says nothing about a fresh copy', () => {
    expect(staleScheduleProblem(SCHEDULE, NOW)).toBeNull();
  });

  it('says nothing when the schedule has no cache timestamp', () => {
    expect(staleScheduleProblem({ ...SCHEDULE, cached_at: undefined }, NOW)).toBeNull();
  });
});
