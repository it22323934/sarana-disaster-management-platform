/**
 * Raising a grievance from the device.
 *
 * **This is a right, not a support ticket**, and the screen it drives is written that way:
 * it shows the SLA date up front, it never asks the household to justify raising one, and
 * it works offline like everything else.
 *
 * The one thing this module has to get right is the trilingual description. The server
 * takes `description` as a `{si, ta, en}` object and quotes it back to the household in
 * their own language when the grievance is answered - while a DS officer who may not share
 * that language reads the same record. A household typing in Tamil cannot be asked to also
 * type it in Sinhala, so the app fills the two it cannot know with a marked placeholder
 * rather than the same text three times: a Sinhala officer reading Tamil words in the
 * Sinhala field would have no way to tell it had not been translated.
 */

import { deviceUuid7 } from '../offline/ids.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';
import type { Locale } from '../i18n/index.js';

/** `ledger_svc.repo.base.GRIEVANCE_SUBJECTS`. */
export const GRIEVANCE_SUBJECTS = [
  'ASSESSMENT',
  'ENTITLEMENT',
  'DISBURSEMENT',
  'EXCLUSION',
] as const;

export type GrievanceSubject = (typeof GRIEVANCE_SUBJECTS)[number];

/** `ledger_svc.domain.grievance.SLA_DAYS_BY_SUBJECT`, with its default. */
export const SLA_DAYS: Record<GrievanceSubject, number> = {
  ASSESSMENT: 14,
  ENTITLEMENT: 14,
  // A disputed payment is the urgent kind: the household says money they were told about
  // did not arrive, and every day of that is a day they go without it.
  DISBURSEMENT: 7,
  EXCLUSION: 14,
};

/**
 * The reasons offered as buttons, per subject.
 *
 * Plain language, not categories. They exist so a household does not have to compose a
 * paragraph to be heard, and free text is always available underneath - the buttons are
 * a shortcut, never the whole vocabulary.
 */
export const REASON_KEYS: Record<GrievanceSubject, readonly string[]> = {
  ASSESSMENT: [
    'grievance.reason.damageUnderstated',
    'grievance.reason.itemsMissing',
    'grievance.reason.neverVisited',
    'grievance.reason.wrongHousehold',
  ],
  ENTITLEMENT: [
    'grievance.reason.amountTooLow',
    'grievance.reason.wrongCategory',
    'grievance.reason.calculationUnclear',
  ],
  DISBURSEMENT: [
    'grievance.reason.notReceived',
    'grievance.reason.amountDiffers',
    'grievance.reason.wrongAccount',
  ],
  EXCLUSION: ['grievance.reason.notAssessed', 'grievance.reason.notOnList'],
};

/** What a household typed, and what it is about. */
export interface GrievanceDraft {
  readonly householdId: string;
  readonly subjectType: GrievanceSubject;
  /** The disputed record. Null only for EXCLUSION - being left out has no id. */
  readonly subjectId: string | null;
  /** Zero or more of `REASON_KEYS`, already resolved to the three languages. */
  readonly reasons: readonly { si: string; ta: string; en: string }[];
  readonly freeText: string;
  /** The language the free text is actually in. */
  readonly language: Locale;
}

export class GrievanceRefused extends Error {}

/**
 * Marks a language the household did not write in.
 *
 * Not left blank: the server requires all three and a blank would be a lie by omission.
 * Not the same text copied: a Sinhala officer reading Tamil words in the Sinhala field has
 * no way to tell it was never translated, and would answer as though they had understood
 * it.
 */
export const UNTRANSLATED_PREFIX = '[untranslated]';

const LOCALES: readonly Locale[] = ['si', 'ta', 'en'];

/**
 * Build the `{si, ta, en}` description.
 *
 * The chosen reasons are already trilingual - they came from the catalogue - so they
 * appear properly in every language. The free text appears in the language it was typed
 * in and is marked in the other two.
 */
export function describe(draft: GrievanceDraft): { si: string; ta: string; en: string } {
  const description = {} as Record<Locale, string>;

  for (const locale of LOCALES) {
    const parts = draft.reasons.map((reason) => reason[locale]).filter(Boolean);
    const text = draft.freeText.trim();
    if (text.length > 0) {
      parts.push(locale === draft.language ? text : `${UNTRANSLATED_PREFIX} (${draft.language}) ${text}`);
    }
    description[locale] = parts.join('. ');
  }

  return { si: description.si, ta: description.ta, en: description.en };
}

/** When the platform owes this household an answer. */
export function slaDueAt(subject: GrievanceSubject, raisedAt: number): number {
  return raisedAt + SLA_DAYS[subject] * 86_400_000;
}

export interface SavedGrievance {
  readonly localId: string;
  readonly clientOperationId: string;
  readonly slaDueAt: number;
}

/**
 * Queue a grievance. Works offline, like everything else.
 *
 * The SLA clock the household is shown starts now, from the device. The server will stamp
 * its own from when the grievance actually arrives, and the two differ by however long the
 * device was offline - which is why the confirmation says "we owe you an answer by" with
 * the date rather than "in 14 days" with a countdown that would silently restart on sync.
 */
export async function saveGrievance(
  log: OperationLog,
  draft: GrievanceDraft,
  { now = Date.now() }: { now?: number } = {},
): Promise<SavedGrievance> {
  if (draft.subjectType !== 'EXCLUSION' && draft.subjectId === null) {
    throw new GrievanceRefused(
      `a grievance about a ${draft.subjectType.toLowerCase()} has to name which one. ` +
        'Only EXCLUSION has no record to point at - being left out has no id.',
    );
  }

  const description = describe(draft);
  if (description.en.trim().length === 0) {
    throw new GrievanceRefused(
      'a grievance needs a reason or some text. An empty one cannot be investigated and ' +
        'would consume an SLA the household is entitled to.',
    );
  }

  const localId = `grv_${deviceUuid7(now)}`;

  const record = await log.append(
    {
      entity_type: 'grievance',
      entity_local_id: localId,
      op: 'create',
      payload: {
        household_id: draft.householdId,
        subject_type: draft.subjectType,
        subject_id: draft.subjectId,
        channel: 'APP',
        description,
      },
    },
    async (_tx: Database) => {
      // No local table. A grievance is read back from the server once it syncs, and a
      // second copy on the device would be a second place for its status to be wrong -
      // the one thing a household checks is whether it has been answered.
    },
  );

  return {
    localId,
    clientOperationId: record.client_operation_id,
    slaDueAt: slaDueAt(draft.subjectType, now),
  };
}
