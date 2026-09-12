/**
 * One device, wired up.
 *
 * Every integration test in `test/` builds one of these and then does to it what a flood
 * does to a handset: takes the network away, kills it mid-batch, fills the disk. The
 * database is real SQLite running the real migrations, so a CHECK constraint that would
 * reject a status on a phone rejects it here too.
 */

import { migrate } from '../src/offline/db/schema.js';
import type { Database } from '../src/offline/db/types.js';
import { MediaQueue } from '../src/offline/media/queue.js';
import { OperationLog } from '../src/offline/log/operation-log.js';
import { SyncEngine } from '../src/offline/sync/engine.js';
import { FakeNetwork, FakeServer, TestClock, WIFI } from './fakes.js';
import { openTestDatabase } from './node-database.js';
import type { NetworkState } from '../src/offline/sync/connectivity.js';

export interface Device {
  readonly db: Database;
  readonly log: OperationLog;
  readonly media: MediaQueue;
  readonly engine: SyncEngine;
  readonly server: FakeServer;
  readonly network: FakeNetwork;
  readonly clock: TestClock;
  /** Write one assessment, exactly as the Field Companion form does. */
  saveAssessment(overrides?: Partial<AssessmentDraft>): Promise<string>;
  close(): Promise<void>;
}

export interface AssessmentDraft {
  household_id: string;
  gn_division_id: string;
  gn_division_code: string;
  hazard_event_id: string;
  category: string;
  subcategory: string;
  cost_estimate_lkr_cents: number;
  latitude: number | null;
  longitude: number | null;
  gps_accuracy_m: number | null;
}

const DRAFT: AssessmentDraft = {
  household_id: '018f4a2b-0000-7000-8000-000000000001',
  gn_division_id: '018f4a2b-0000-7000-8000-000000000002',
  gn_division_code: 'LK-2-05-020-1015',
  hazard_event_id: '018f4a2b-0000-7000-8000-000000000003',
  category: 'HOUSE_PARTIAL',
  subcategory: '',
  cost_estimate_lkr_cents: 185_000_00,
  latitude: 7.2906,
  longitude: 80.6337,
  gps_accuracy_m: 12,
};

export async function makeDevice(
  options: {
    deviceId?: string;
    network?: NetworkState;
    server?: FakeServer;
    batchSize?: number;
  } = {},
): Promise<Device> {
  const db = openTestDatabase();
  await migrate(db);

  const clock = new TestClock();
  const log = new OperationLog(db, clock);
  const media = new MediaQueue(db, clock);
  const server = options.server ?? new FakeServer();
  const network = new FakeNetwork(options.network ?? WIFI);

  await log.register(options.deviceId ?? 'device-kandy-01');

  const engine = new SyncEngine({
    log,
    media,
    transport: server,
    network,
    clock,
    batchSize: options.batchSize ?? 50,
    // Deterministic: the backoff's own randomness is tested in backoff.test.ts, and a
    // sync test that failed one time in fifty because of a jitter draw would be worse
    // than no test.
    backoff: { random: () => 0.5 },
  });

  let counter = 0;

  return {
    db,
    log,
    media,
    engine,
    server,
    network,
    clock,
    async saveAssessment(overrides = {}) {
      counter += 1;
      const draft = { ...DRAFT, ...overrides };
      const localId = `asm_local_${counter}`;
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
            subcategory: draft.subcategory,
            cost_estimate_lkr_cents: draft.cost_estimate_lkr_cents,
            assessed_at: new Date(clock.now()).toISOString(),
            latitude: draft.latitude,
            longitude: draft.longitude,
            gps_accuracy_m: draft.gps_accuracy_m,
          },
        },
        async (tx) => {
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
              draft.subcategory,
              draft.cost_estimate_lkr_cents,
              new Date(clock.now()).toISOString(),
              draft.latitude,
              draft.longitude,
              draft.gps_accuracy_m,
              'SUBMITTED',
              new Date(clock.now()).toISOString(),
            ],
          );
        },
      );
      return record.client_operation_id;
    },
    async close() {
      await engine.stop();
      await db.close();
    },
  };
}
