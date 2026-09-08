/**
 * Writing one damage assessment to the device.
 *
 * The one write path the Field Companion has, and the shape every other write in this app
 * copies: the entity row and the operation that will sync it go in together, in one
 * transaction. A device holding an assessment with no operation has work it will never
 * sync and no way to know.
 *
 * The payload is the server's `AssessmentPayload`, field for field. It is not remodelled
 * on the way out: the sync contract's safety property is that the same key means the same
 * thing at both ends, and a device that renames a field has to rename it back.
 */

import { deviceUuid7 } from '../offline/ids.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';

/**
 * The nine categories `ledger_svc.repo.base.DAMAGE_CATEGORIES` accepts.
 *
 * A category this list has and the server does not comes back as a conflict with
 * `reason: unknown_category`, which jams the device's queue until a person looks at it.
 * `test/vocabulary.test.ts` holds the two lists together.
 */
export const DAMAGE_CATEGORIES = [
  'HOUSE_FULL',
  'HOUSE_PARTIAL',
  'HOUSEHOLD_GOODS',
  'LIVELIHOOD_TOOLS',
  'CROP',
  'LIVESTOCK',
  'FISHING_GEAR',
  'DEATH',
  'INJURY',
] as const;

export type DamageCategory = (typeof DAMAGE_CATEGORIES)[number];

export interface AssessmentDraft {
  readonly household_id: string;
  readonly gn_division_id: string;
  readonly gn_division_code: string;
  readonly hazard_event_id: string;
  readonly category: DamageCategory;
  readonly subcategory?: string;
  readonly cost_estimate_lkr_cents: number;
  /** Where the officer stood, not where the household is. One input to anomaly detection. */
  readonly latitude?: number | null;
  readonly longitude?: number | null;
  readonly gps_accuracy_m?: number | null;
}

export interface SavedAssessment {
  readonly localId: string;
  readonly clientOperationId: string;
}

/**
 * Save a draft. Returns as soon as SQLite has it, which is the point.
 *
 * Nothing here touches the network. The UI reads the row back immediately and the sync
 * engine catches up whenever it can - a GN officer who taps Save and waits for a spinner
 * during a flood has been failed by the design.
 */
export async function saveAssessment(
  log: OperationLog,
  draft: AssessmentDraft,
  { now = Date.now() }: { now?: number } = {},
): Promise<SavedAssessment> {
  const localId = `asm_${deviceUuid7(now)}`;
  const assessedAt = new Date(now).toISOString();

  const record = await log.append(
    {
      entity_type: 'assessment',
      entity_local_id: localId,
      op: 'create',
      payload: {
        household_id: draft.household_id,
        gn_division_id: draft.gn_division_id,
        gn_division_code: draft.gn_division_code,
        hazard_event_id: draft.hazard_event_id,
        category: draft.category,
        subcategory: draft.subcategory ?? '',
        cost_estimate_lkr_cents: draft.cost_estimate_lkr_cents,
        assessed_at: assessedAt,
        latitude: draft.latitude ?? null,
        longitude: draft.longitude ?? null,
        gps_accuracy_m: draft.gps_accuracy_m ?? null,
      },
    },
    async (tx: Database) => {
      await tx.execute(
        'INSERT INTO assessment (local_id, household_id, gn_division_id, gn_division_code, ' +
          'hazard_event_id, category, subcategory, cost_estimate_lkr_cents, assessed_at, ' +
          'latitude, longitude, gps_accuracy_m, status, updated_at) ' +
          'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          localId,
          draft.household_id,
          draft.gn_division_id,
          draft.gn_division_code,
          draft.hazard_event_id,
          draft.category,
          draft.subcategory ?? '',
          draft.cost_estimate_lkr_cents,
          assessedAt,
          draft.latitude ?? null,
          draft.longitude ?? null,
          draft.gps_accuracy_m ?? null,
          // Never DRAFT once it is saved: the officer has finished with it, and the
          // server will store it as SUBMITTED. A local status the server cannot produce
          // would show the officer a state that disappears on sync.
          'SUBMITTED',
          assessedAt,
        ],
      );
    },
  );

  return { localId, clientOperationId: record.client_operation_id };
}

/** The draft the debug bridge writes. Seeded Kandy household, seeded hazard event. */
export const SAMPLE_DRAFT: AssessmentDraft = {
  household_id: '018f4a2b-0000-7000-8000-000000000001',
  gn_division_id: '018f4a2b-0000-7000-8000-000000000002',
  gn_division_code: 'LK-2-05-020-1015',
  hazard_event_id: '018f4a2b-0000-7000-8000-000000000003',
  category: 'HOUSE_PARTIAL',
  cost_estimate_lkr_cents: 185_000_00,
  latitude: 7.2906,
  longitude: 80.6337,
  gps_accuracy_m: 12,
};

/** Convenience for the debug bridge, which has a log and nothing else. */
export async function saveAssessmentDraft(
  log: OperationLog,
  draft: AssessmentDraft,
): Promise<string> {
  return (await saveAssessment(log, draft)).clientOperationId;
}
