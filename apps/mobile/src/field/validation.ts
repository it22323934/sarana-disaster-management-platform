/**
 * What the form refuses, on the device, before Save.
 *
 * The brief's rule: "every field is validated against the schedule's bounds **on device**,
 * so an out-of-range value is caught in the field, not three weeks later in a rejection."
 *
 * That timing is the whole reason this file exists rather than the server doing all of it.
 * A rejection three weeks later is a rejection of work that cannot be redone: the water has
 * gone down, the debris has been cleared, and the officer would have to persuade a
 * household to let them photograph a repaired wall. Catching it while the officer is
 * standing there costs thirty seconds.
 *
 * **Every refusal is specific and every one names the bound.** "Invalid value" sends an
 * officer looking through nine fields; "CROP: the schedule pays for at most 5 acres, you
 * entered 9" tells them what to change. A validator that cannot explain itself gets
 * worked around.
 *
 * The server validates all of this again. That is not duplication to be removed — the
 * device's copy is an aid to the officer and the server's is the authority, and a device
 * that could be trusted to be the only check would be a device an attacker could edit.
 */

import { DAMAGE_CATEGORIES } from './assessment-draft.js';
import { lineFor, type AssessedItem, type CostSchedule } from './entitlement.js';

/**
 * A refusal the officer can act on.
 *
 * `field` is what the form focuses; `message` is what it shows. Both are required, because
 * a message with no field is an error the officer cannot navigate to and a field with no
 * message is a red box with no explanation.
 */
export interface ValidationProblem {
  readonly field: string;
  readonly message: string;
  /** `blocking` stops Save. `advisory` is shown and does not. */
  readonly severity: 'blocking' | 'advisory';
}

/**
 * How stale a cached schedule may be before the officer is told.
 *
 * Fourteen days. Not a refusal: a schedule this device pulled a month ago is still the
 * schedule that was published a month ago, and an officer in a cut-off division working
 * from it is doing the right thing. It is an advisory because the officer is the only
 * person who can decide whether to trust it, and they can only decide if they are told.
 */
export const SCHEDULE_STALE_AFTER_DAYS = 14;

/**
 * The accuracy beyond which a GPS fix is not good enough to stand on its own.
 *
 * Fifty metres, from the brief. Below it the fix is accepted silently; above it the officer
 * is asked to wait or place the pin by hand, and which of those happened is recorded.
 *
 * The number is not arbitrary: fifty metres is roughly the width of a village lane, so a
 * fix worse than that cannot distinguish one house from its neighbour — and distinguishing
 * one house from its neighbour is the entire evidentiary value of the coordinate.
 */
export const GPS_ACCURACY_THRESHOLD_M = 50;

/** The two photographs the brief requires: one wide, one detail. */
export const MINIMUM_PHOTOS = 2;

export interface AssessmentFormState {
  readonly householdLocalId: string | null;
  readonly items: readonly AssessedItem[];
  readonly photoCount: number;
  readonly latitude: number | null;
  readonly longitude: number | null;
  readonly gpsAccuracyM: number | null;
  readonly locationSource: 'GPS' | 'MANUAL' | null;
  readonly note?: string | null;
}

export interface ValidationContext {
  readonly schedule: CostSchedule;
  readonly now: number;
  /** The division the capability token is pinned to. */
  readonly division: string;
  readonly householdDivision?: string | null;
}

/**
 * Check one line item against the schedule that will price it.
 *
 * Split out so the form can validate a row the moment the officer leaves it, rather than
 * only on Save. The category check comes first: a units message about a category the
 * schedule does not price would be answering the wrong question.
 */
export function validateItem(
  item: AssessedItem,
  index: number,
  schedule: CostSchedule,
): ValidationProblem[] {
  const problems: ValidationProblem[] = [];
  const field = `items[${index}]`;

  if (!(DAMAGE_CATEGORIES as readonly string[]).includes(item.category)) {
    problems.push({
      field: `${field}.category`,
      severity: 'blocking',
      // Named rather than generic: a category the device allows and the server does not
      // comes back as a conflict that jams the whole queue behind it, so it must never
      // leave the handset.
      message:
        `'${item.category}' is not a damage category this platform records. Choose one of ` +
        'the nine on the form.',
    });
    return problems;
  }

  let line;
  try {
    line = lineFor(schedule, item.category);
  } catch {
    problems.push({
      field: `${field}.category`,
      severity: 'blocking',
      message:
        `The ${schedule.version} schedule on this device does not price ${item.category}. ` +
        'Sync to pick up a newer schedule, or record this category on a paper form.',
    });
    return problems;
  }

  if (!Number.isInteger(item.units)) {
    problems.push({
      field: `${field}.units`,
      severity: 'blocking',
      message: 'Enter a whole number.',
    });
  } else if (item.units < 0) {
    problems.push({
      field: `${field}.units`,
      severity: 'blocking',
      message: 'A quantity cannot be negative.',
    });
  } else if (item.units > line.max_units) {
    problems.push({
      field: `${field}.units`,
      severity: 'blocking',
      // The bound is in the message. This is the case the brief names, and the officer
      // needs the ceiling to decide whether they mis-typed or the schedule is wrong.
      message:
        `The ${schedule.version} schedule pays for at most ${line.max_units} for ` +
        `${item.category}. You entered ${item.units}.`,
    });
  }

  return problems;
}

/**
 * Everything that stops this assessment being saved, and everything worth saying about it.
 *
 * Ordered by where the officer will look: household, then items, then evidence, then
 * location. A list that put the GPS warning above a missing household would send them to
 * the bottom of the form to fix the thing at the top.
 */
export function validateAssessment(
  state: AssessmentFormState,
  context: ValidationContext,
): ValidationProblem[] {
  const problems: ValidationProblem[] = [];

  if (!state.householdLocalId) {
    problems.push({
      field: 'household',
      severity: 'blocking',
      message: 'Select a household, or create one if the register does not have it.',
    });
  }

  if (context.householdDivision && context.householdDivision !== context.division) {
    problems.push({
      field: 'household',
      severity: 'blocking',
      // Caught here rather than on sync, because the capability token is pinned to one
      // division and the server would refuse the operation three days later - by which
      // time the officer has left.
      message:
        `This household is in ${context.householdDivision} and your offline permit covers ` +
        `${context.division}. The assessment would be refused when it syncs.`,
    });
  }

  if (state.items.length === 0) {
    problems.push({
      field: 'items',
      severity: 'blocking',
      message: 'Add at least one damage category.',
    });
  }

  state.items.forEach((item, index) => {
    problems.push(...validateItem(item, index, context.schedule));
  });

  if (state.photoCount < MINIMUM_PHOTOS) {
    problems.push({
      field: 'photos',
      severity: 'blocking',
      // The reason is in the message because officers reasonably ask why two. Six months
      // later, at audit, one photograph of a wall is not evidence of which wall.
      message:
        `Take ${MINIMUM_PHOTOS} photographs: one wide shot showing the building, one close ` +
        'shot showing the damage. They are what makes this record defensible at audit.',
    });
  }

  if (state.latitude === null || state.longitude === null) {
    problems.push({
      field: 'location',
      severity: 'blocking',
      message: 'Wait for a location fix, or place the pin on the map by hand.',
    });
  } else if (state.locationSource === 'GPS' && (state.gpsAccuracyM ?? Infinity) > GPS_ACCURACY_THRESHOLD_M) {
    problems.push({
      field: 'location',
      severity: 'blocking',
      message:
        `The fix is accurate to ${Math.round(state.gpsAccuracyM ?? 0)}m, which cannot tell ` +
        `this house from its neighbour. Wait for it to improve below ` +
        `${GPS_ACCURACY_THRESHOLD_M}m, or place the pin by hand.`,
    });
  }

  const stale = staleScheduleProblem(context.schedule, context.now);
  if (stale) problems.push(stale);

  return problems;
}

/** Whether the cached schedule is old enough to mention. Advisory, never blocking. */
export function staleScheduleProblem(
  schedule: CostSchedule,
  now: number,
): ValidationProblem | null {
  if (!schedule.cached_at) return null;

  const ageDays = (now - Date.parse(schedule.cached_at)) / 86_400_000;
  if (!Number.isFinite(ageDays) || ageDays < SCHEDULE_STALE_AFTER_DAYS) return null;

  return {
    field: 'schedule',
    severity: 'advisory',
    message:
      `This device's copy of the ${schedule.version} schedule is ${Math.floor(ageDays)} days ` +
      'old. The provisional figure may not match what the household is finally awarded.',
  };
}

/** Whether the form may be saved. Advisory problems do not stop it. */
export function maySave(problems: readonly ValidationProblem[]): boolean {
  return !problems.some((problem) => problem.severity === 'blocking');
}
