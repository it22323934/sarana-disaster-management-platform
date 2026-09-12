/**
 * Saving one assessment: the entity, its items, its operation and its photos, atomically.
 *
 * The brief's step seven: "lands in SQLite instantly, enters the sync queue, and the
 * officer moves on. No spinner, no wait, no network call in the interaction path." Nothing
 * in this file touches the network, and the function returns as soon as the transaction
 * commits.
 *
 * `field/assessment-draft.ts` already wrote the single-category form file 22 needed. This
 * is the multi-item form the assessment screen actually uses, and it keeps that module's
 * one rule: **the entity row and the operation that syncs it go in together, in one
 * transaction.** A device holding an assessment with no operation has work it will never
 * sync and no way to know it.
 *
 * Two things are recorded that the server does not currently read, and both are deliberate:
 *
 *   **The line items.** `POST /entitlements` values one schedule line today — a known gap
 *   carried since file 10 — so the synced payload still names one category. The items are
 *   written locally anyway, because the officer's assessment *is* several items and
 *   throwing that away at the device boundary would mean re-surveying when the endpoint
 *   catches up.
 *
 *   **The provisional entitlement and its trace.** The server recomputes and its answer is
 *   authoritative. Keeping what the device showed means a later disagreement can be traced
 *   to what the officer was told at the time, rather than argued about.
 */

import type { Database } from '../offline/db/types.js';
import type { MediaQueue } from '../offline/media/queue.js';
import type { OperationLog } from '../offline/log/operation-log.js';
import { deviceUuid7 } from '../offline/ids.js';
import { calculate, type AssessedItem, type CostSchedule } from './entitlement.js';
import type { AssessmentSource } from './paper-form.js';
import { maySave, validateAssessment, type ValidationProblem } from './validation.js';

/** A photograph taken for this assessment, already written to the device's filesystem. */
export interface AssessmentPhoto {
  readonly localUri: string;
  readonly contentType: string;
  readonly sizeBytes: number;
  /**
   * Lifted from the file's EXIF and then stripped from the file itself (file 22).
   *
   * The coordinate is evidence and belongs in a column a reviewer can see. Leaving it
   * embedded in an image that may later be shown to a review board is how a household's
   * address leaks out of the platform sideways.
   */
  readonly latitude?: number | null;
  readonly longitude?: number | null;
  /**
   * A perceptual hash, computed on device.
   *
   * Not a checksum: two photographs of the same wall from slightly different angles have
   * different SHA-256s and near-identical perceptual hashes. It is what lets the anomaly
   * agent (file 17) notice the same photograph submitted for two households without ever
   * comparing the images themselves.
   */
  readonly perceptualHash?: string | null;
  readonly kind: 'wide' | 'detail' | 'paper-form';
}

export interface AssessmentInput {
  readonly householdId: string;
  readonly householdLocalId: string;
  readonly gnDivisionId: string;
  readonly gnDivisionCode: string;
  readonly hazardEventId: string;
  readonly items: readonly AssessedItem[];
  readonly photos: readonly AssessmentPhoto[];
  readonly latitude: number;
  readonly longitude: number;
  readonly gpsAccuracyM: number | null;
  readonly locationSource: 'GPS' | 'MANUAL';
  readonly source: AssessmentSource;
  readonly note?: string | null;
  readonly alreadyDisbursedCents?: number;
}

export interface SavedAssessment {
  readonly localId: string;
  readonly clientOperationId: string;
  readonly provisionalEntitlementCents: number;
  readonly mediaIds: readonly string[];
}

export class AssessmentRefused extends Error {
  constructor(readonly problems: readonly ValidationProblem[]) {
    super(
      `the assessment cannot be saved: ${problems
        .filter((problem) => problem.severity === 'blocking')
        .map((problem) => problem.message)
        .join(' ')}`,
    );
    this.name = 'AssessmentRefused';
  }
}

/**
 * Which category syncs while the server still values one line.
 *
 * The largest item by value, not the first entered. If only one number can be sent, it
 * should be the one that dominates the household's entitlement — sending `HOUSEHOLD_GOODS`
 * because the officer happened to tap it first, while the house is destroyed, would
 * understate the claim by an order of magnitude.
 *
 * Exported because the reviewer's screen needs to say which line was sent and the test
 * needs to assert it.
 */
export function dominantItem(
  items: readonly AssessedItem[],
  schedule: CostSchedule,
): AssessedItem | null {
  let best: AssessedItem | null = null;
  let bestValue = -1;

  for (const item of items) {
    const line = schedule.lines[item.category];
    if (!line) continue;
    const value = Math.min(item.units, line.max_units) * line.unit_amount_cents;
    // Strictly greater, so a tie keeps the earlier item and the choice is deterministic.
    if (value > bestValue) {
      best = item;
      bestValue = value;
    }
  }

  return best;
}

/**
 * Save an assessment. Returns once SQLite has it.
 *
 * Validation runs first and refuses rather than saving something the server will reject:
 * an out-of-range value stored locally is a queue that jams three days later, in a division
 * the officer has already left.
 */
export async function saveFieldAssessment(
  {
    log,
    media,
    schedule,
  }: {
    readonly log: OperationLog;
    readonly media: MediaQueue;
    readonly schedule: CostSchedule;
    /**
     * No `db` here on purpose.
     *
     * Every write this function makes goes through the transaction handle `log.append`
     * supplies, which is what keeps the entity row and its operation atomic. Taking a
     * second handle would let a future edit write outside that transaction, which is
     * exactly the bug the pairing exists to prevent - an assessment with no operation to
     * sync it, and no way for the device to know.
     */
  },
  input: AssessmentInput,
  { now = Date.now(), division }: { now?: number; division?: string } = {},
): Promise<SavedAssessment> {
  const problems = validateAssessment(
    {
      householdLocalId: input.householdLocalId,
      items: input.items,
      photoCount: input.photos.length,
      latitude: input.latitude,
      longitude: input.longitude,
      gpsAccuracyM: input.gpsAccuracyM,
      locationSource: input.locationSource,
      note: input.note ?? null,
    },
    {
      schedule,
      now,
      division: division ?? input.gnDivisionCode,
      householdDivision: input.gnDivisionCode,
    },
  );

  if (!maySave(problems)) throw new AssessmentRefused(problems);

  const trace = calculate(input.items, schedule, {
    alreadyDisbursedCents: input.alreadyDisbursedCents ?? 0,
  });

  const localId = `asm_${deviceUuid7(now)}`;
  const assessedAt = new Date(now).toISOString();
  const dominant = dominantItem(input.items, schedule);
  if (!dominant) {
    throw new AssessmentRefused([
      {
        field: 'items',
        severity: 'blocking',
        message: 'None of the categories entered is priced by the schedule on this device.',
      },
    ]);
  }

  const record = await log.append(
    {
      entity_type: 'assessment',
      entity_local_id: localId,
      op: 'create',
      payload: {
        household_id: input.householdId,
        gn_division_id: input.gnDivisionId,
        gn_division_code: input.gnDivisionCode,
        hazard_event_id: input.hazardEventId,
        // The single category the sync contract carries today. See `dominantItem`.
        category: dominant.category,
        subcategory: '',
        cost_estimate_lkr_cents: trace.result_lkr_cents,
        assessed_at: assessedAt,
        latitude: input.latitude,
        longitude: input.longitude,
        gps_accuracy_m: input.gpsAccuracyM,
      },
    },
    async (tx: Database) => {
      await tx.execute(
        'INSERT INTO assessment (local_id, household_id, gn_division_id, gn_division_code, ' +
          'hazard_event_id, category, subcategory, cost_estimate_lkr_cents, assessed_at, ' +
          'latitude, longitude, gps_accuracy_m, status, updated_at, source, location_source, ' +
          'provisional_entitlement_cents, provisional_trace, cost_schedule_version, note) ' +
          'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          localId,
          input.householdId,
          input.gnDivisionId,
          input.gnDivisionCode,
          input.hazardEventId,
          dominant.category,
          '',
          trace.result_lkr_cents,
          assessedAt,
          input.latitude,
          input.longitude,
          input.gpsAccuracyM,
          // Never DRAFT once saved: the officer has finished with it and the server stores
          // it as SUBMITTED. A local status the server cannot produce would show a state
          // that vanishes on sync.
          'SUBMITTED',
          assessedAt,
          input.source,
          input.locationSource,
          trace.result_lkr_cents,
          JSON.stringify(trace),
          schedule.version,
          input.note ?? null,
        ],
      );

      for (const item of input.items) {
        await tx.execute(
          'INSERT INTO assessment_item (id, assessment_local_id, category, subcategory, ' +
            'units, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
          [`itm_${deviceUuid7(now)}`, localId, item.category, '', item.units, null, assessedAt],
        );
      }
    },
  );

  // Photos enqueue after the transaction commits, not inside it.
  //
  // The metadata is what matters: an assessment visible to a reviewer with its photos still
  // uploading is useful, and a photo with no assessment is not. If the app dies between the
  // two, the officer has the assessment and the photo files are still on disk - recoverable,
  // where a rolled-back assessment would not be.
  const mediaIds: string[] = [];
  for (const photo of input.photos) {
    const enqueued = await media.enqueue({
      client_operation_id: record.client_operation_id,
      entity_type: 'assessment',
      entity_local_id: localId,
      kind: 'photo',
      local_uri: photo.localUri,
      content_type: photo.contentType,
      size_bytes: photo.sizeBytes,
      sha256: photo.perceptualHash ?? null,
      latitude: photo.latitude ?? null,
      longitude: photo.longitude ?? null,
    });
    mediaIds.push(enqueued.id);
  }

  return {
    localId,
    clientOperationId: record.client_operation_id,
    provisionalEntitlementCents: trace.result_lkr_cents,
    mediaIds,
  };
}

/** The items of one assessment, for the detail screen. */
export async function itemsFor(
  db: Database,
  assessmentLocalId: string,
): Promise<{ category: string; units: number }[]> {
  return db.select<{ category: string; units: number }>(
    'SELECT category, units FROM assessment_item WHERE assessment_local_id = ? ORDER BY category',
    [assessmentLocalId],
  );
}
