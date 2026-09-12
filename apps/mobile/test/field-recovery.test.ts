/**
 * The two recovery paths: a conflict the officer must decide, and a queue carried to
 * another handset. `pnpm --filter mobile test -- field`
 *
 * The brief's fifth and sixth test cases. Both are about a device that has stopped being
 * able to do the normal thing, which in a three-month recovery is a scenario with a date
 * on it rather than an edge case.
 */

import { describe, expect, it } from 'vitest';

import { exportQueue } from '../src/offline/export.js';
import { migrate } from '../src/offline/db/schema.js';
import { MediaQueue } from '../src/offline/media/queue.js';
import { OperationLog } from '../src/offline/log/operation-log.js';
import { SyncEngine } from '../src/offline/sync/engine.js';
import {
  CONFLICT_REASONS,
  choicesFor,
  describeConflict,
  mayAutoResolve,
} from '../src/field/conflicts.js';
import { QueueImportRefused, importQueue, readExport } from '../src/field/queue-import.js';
import { AIRPLANE, FakeNetwork, FakeServer, TestClock, WIFI } from '../test-support/fakes.js';
import { makeDevice } from '../test-support/harness.js';
import { openTestDatabase } from '../test-support/node-database.js';

describe('a conflict is surfaced and requires an explicit choice', () => {
  it('never resolves itself', () => {
    // Named rather than absent, so a future change that wants to auto-merge has to delete
    // this and read why it is here. No rule can pick correctly: the officer was in the
    // division and the server was not.
    expect(mayAutoResolve()).toBe(false);
  });

  it('shows the local record beside the server record', () => {
    const summary = describeConflict({
      client_operation_id: 'op-1',
      seq: 4,
      entity_type: 'assessment',
      entity_local_id: 'asm_1',
      op: 'create',
      payload: JSON.stringify({
        household_id: 'hh-1',
        category: 'HOUSE_FULL',
        cost_estimate_lkr_cents: 250_000_00,
      }),
      created_at: '2026-09-08T06:00:00Z',
      synced_at: null,
      server_id: null,
      status: 'conflict',
      attempt_count: 1,
      last_error: 'an assessment already exists for this household',
      conflict_detail: JSON.stringify({
        reason: 'assessment_already_exists',
        server: { category: 'HOUSE_PARTIAL', cost_estimate_lkr_cents: 75_000_00 },
      }),
    });

    expect(summary.reason).toBe('assessment_already_exists');

    const category = summary.fields.find((field) => field.field === 'category');
    expect(category?.local).toBe('HOUSE_FULL');
    expect(category?.server).toBe('HOUSE_PARTIAL');
    expect(category?.differs).toBe(true);

    // Fields the server said nothing about are still listed, so the officer sees the whole
    // record rather than a diff of the parts a rule found interesting.
    const household = summary.fields.find((field) => field.field === 'household_id');
    expect(household?.server).toBeNull();
    expect(household?.differs).toBe(false);
  });

  it('offers accept-server only where the server holds a competing record', () => {
    // Offering "accept the server's version" for a household the server has never heard of
    // would mean "accept nothing", which is `discard` under a misleading label.
    expect(choicesFor('assessment_already_exists')).toContain('accept-server');
    expect(choicesFor('household_not_found')).not.toContain('accept-server');
    // Keeping the local record is always on offer, because the officer was there.
    for (const reason of CONFLICT_REASONS) {
      expect(choicesFor(reason)).toContain('keep-local');
    }
  });

  it('explains an unknown reason in the server’s own words rather than generically', () => {
    const summary = describeConflict({
      client_operation_id: 'op-2',
      seq: 5,
      entity_type: 'assessment',
      entity_local_id: 'asm_2',
      op: 'create',
      payload: '{}',
      created_at: '2026-09-08T06:00:00Z',
      synced_at: null,
      server_id: null,
      status: 'conflict',
      attempt_count: 1,
      last_error: 'the hazard event was closed before this assessment was filed',
      conflict_detail: JSON.stringify({ reason: 'hazard_event_closed' }),
    });

    expect(summary.reason).toBe('unknown');
    expect(summary.explanation).toBe(
      'the hazard event was closed before this assessment was filed',
    );
  });

  it('still describes an operation whose payload will not parse', () => {
    // It is jamming the queue, so the officer has to be told about it. Suppressing it
    // because it cannot be rendered side by side would hide the reason nothing is syncing.
    const summary = describeConflict({
      client_operation_id: 'op-3',
      seq: 6,
      entity_type: 'assessment',
      entity_local_id: 'asm_3',
      op: 'create',
      payload: 'not json at all',
      created_at: '2026-09-08T06:00:00Z',
      synced_at: null,
      server_id: null,
      status: 'conflict',
      attempt_count: 1,
      last_error: 'refused',
      conflict_detail: null,
    });

    expect(summary.fields).toEqual([]);
    expect(summary.clientOperationId).toBe('op-3');
  });

  it('jams the queue behind it, and says how much is waiting', async () => {
    // The server does not advance `applied_seq` past a refusal, and the device mirrors it.
    // Skipping would rebuild a household's record out of an update whose create never
    // arrived - so the officer needs to know a conflict is holding up the rest of the day.
    const device = await makeDevice({ network: AIRPLANE });
    for (let index = 0; index < 4; index += 1) await device.saveAssessment();

    const records = await device.log.all();
    const summary = describeConflict(
      { ...records[1]!, status: 'conflict', conflict_detail: JSON.stringify({ reason: 'unknown_category' }) },
      { blocking: 2 },
    );
    expect(summary.blocking).toBe(2);

    await device.close();
  });
});

describe('the queue export can be re-imported and applied', () => {
  it('carries the work onto a replacement handset', async () => {
    // The failing-device path: a handset with a dying battery three weeks into a recovery,
    // holding assessments that have never synced. The file is the only route the work has.
    const failing = await makeDevice({ network: AIRPLANE, deviceId: 'device-failing' });
    for (let index = 0; index < 5; index += 1) await failing.saveAssessment();

    const file = await exportQueue(failing.log);
    expect(file.operations).toHaveLength(5);

    const replacement = await makeDevice({ network: AIRPLANE, deviceId: 'device-replacement' });
    const report = await importQueue(replacement.db, replacement.log, readExport(file));

    expect(report.applied).toBe(5);
    expect(report.skipped).toBe(0);
    expect(report.refused).toEqual([]);
    expect(report.sourceDeviceId).toBe('device-failing');

    // And the replacement can sync them.
    replacement.network.set(WIFI);
    await replacement.engine.refreshNow();
    expect(replacement.server.assessments.size).toBe(5);

    await failing.close();
    await replacement.close();
  });

  it('is idempotent, because the officer will import it twice', async () => {
    // They will not be sure the first attempt worked. A duplicate here is two payments
    // against one household, which is why the original client operation id is preserved
    // rather than a new one minted on import.
    const failing = await makeDevice({ network: AIRPLANE, deviceId: 'device-failing-2' });
    for (let index = 0; index < 3; index += 1) await failing.saveAssessment();
    const file = await exportQueue(failing.log);

    const replacement = await makeDevice({ network: AIRPLANE, deviceId: 'device-replacement-2' });
    await importQueue(replacement.db, replacement.log, readExport(file));
    const second = await importQueue(replacement.db, replacement.log, readExport(file));

    expect(second.applied).toBe(0);
    expect(second.skipped).toBe(3);

    replacement.network.set(WIFI);
    await replacement.engine.refreshNow();
    expect(replacement.server.assessments.size).toBe(3);

    await failing.close();
    await replacement.close();
  });

  it('keeps the original operation ids, so the failing handset cannot double-submit', async () => {
    // The case that makes the whole path safe. If the dying phone reaches a signal after
    // the import, the server sees the same idempotency key and stores one record.
    const failing = await makeDevice({ network: AIRPLANE, deviceId: 'device-failing-3' });
    await failing.saveAssessment();
    const file = await exportQueue(failing.log);

    const server = new FakeServer();
    const replacement = await makeDevice({
      network: WIFI,
      deviceId: 'device-replacement-3',
      server,
    });
    await importQueue(replacement.db, replacement.log, readExport(file));
    await replacement.engine.refreshNow();
    expect(server.assessments.size).toBe(1);

    // The old handset wakes up on the same server.
    const revived = await makeDevice({ network: WIFI, deviceId: 'device-failing-3b', server });
    await importQueue(revived.db, revived.log, readExport(file));
    await revived.engine.refreshNow();

    expect(server.assessments.size).toBe(1);

    await failing.close();
    await replacement.close();
    await revived.close();
  });

  it('names a row it cannot read rather than discarding the other thirty-nine', async () => {
    const replacement = await makeDevice({ network: AIRPLANE, deviceId: 'device-replacement-4' });
    const report = await importQueue(replacement.db, replacement.log, {
      exported_at: '2026-09-08T06:00:00Z',
      device_id: 'device-failing-4',
      server_cursor: 0,
      schema_version: 1,
      note: '',
      operations: [
        {
          client_operation_id: 'good-1',
          seq: 1,
          entity_type: 'assessment',
          op: 'create',
          status: 'pending',
          created_at: '2026-09-08T06:00:00Z',
          attempt_count: 0,
          last_error: null,
          conflict_detail: null,
          payload: { household_id: 'hh-1' },
        },
        {
          client_operation_id: 'corrupt-1',
          seq: 2,
          entity_type: 'assessment',
          op: 'create',
          status: 'pending',
          created_at: '2026-09-08T06:00:00Z',
          attempt_count: 0,
          last_error: null,
          conflict_detail: null,
          // What `exportQueue` writes for a payload that would not parse on the source.
          payload: { unreadable: true, raw: 'not json' } as unknown as Record<string, unknown>,
        },
        {
          client_operation_id: 'wrong-kind-1',
          seq: 3,
          entity_type: 'spreadsheet',
          op: 'create',
          status: 'pending',
          created_at: '2026-09-08T06:00:00Z',
          attempt_count: 0,
          last_error: null,
          conflict_detail: null,
          payload: {},
        },
      ],
    } as never);

    // The good row is saved. A recovery path that gave up on the first bad row would
    // discard the work it exists to save.
    expect(report.applied).toBe(1);

    // Both bad rows are named, and the corrupt one matters most.
    //
    // `{ unreadable: true, raw: ... }` is an object, so an importer that only checked the
    // payload's *type* would apply it as though it were an assessment — and the server
    // would refuse it as a conflict that then jams the queue on the replacement handset.
    // The recovery path would have carried the failure across along with the work. That is
    // what this assertion is holding in place.
    expect(report.refused.map((entry) => entry.clientOperationId)).toEqual([
      'corrupt-1',
      'wrong-kind-1',
    ]);
    expect(report.refused[0]?.reason).toContain('could not be read');

    await replacement.close();
  });

  it('refuses a file written by a newer app rather than dropping its fields', async () => {
    const replacement = await makeDevice({ network: AIRPLANE, deviceId: 'device-replacement-5' });
    expect(() =>
      readExport({ device_id: 'd', operations: [], schema_version: 99, exported_at: '', note: '', server_cursor: 0 }),
    ).toThrow(QueueImportRefused);
    await replacement.close();
  });

  it('refuses a file that is not an export at all, and says what to do', () => {
    // The officer will pick the wrong file. The message decides whether they try again.
    try {
      readExport({ photos: [] });
      expect.unreachable('it must refuse');
    } catch (error) {
      expect((error as Error).message).toContain('Export again');
    }
  });
});

describe('the exported file still carries no credentials', () => {
  it('contains no token, key or session, even after the field surface added columns', async () => {
    // File 22 asserted this. Repeated here because file 24 added `source`,
    // `provisional_trace` and the household register, and an export that started carrying
    // a decrypted name would be a register leak in a file the officer emails to a district
    // office.
    const device = await makeDevice({ network: AIRPLANE });
    await device.saveAssessment();

    const serialised = JSON.stringify(await exportQueue(device.log));
    for (const forbidden of ['token', 'secret', 'key', 'session']) {
      expect(serialised.toLowerCase()).not.toContain(`"${forbidden}"`);
    }
    await device.close();
  });
});

describe('the import writes through the real log', () => {
  it('leaves the imported operations claimable by the sync engine', async () => {
    // Not a mock: the imported rows go through `OperationLog.append`, so they are subject
    // to the same CHECK constraints and the same batch planner as anything the officer
    // typed. An import that wrote rows the engine would not claim would look like success
    // and sync nothing.
    const db = openTestDatabase();
    await migrate(db);
    const clock = new TestClock();
    const log = new OperationLog(db, clock);
    const media = new MediaQueue(db, clock);
    const server = new FakeServer();
    const engine = new SyncEngine({
      log,
      media,
      transport: server,
      network: new FakeNetwork(WIFI),
      clock,
      batchSize: 50,
      backoff: { random: () => 0.5 },
    });
    await log.register('device-import-engine');

    await importQueue(db, log, {
      exported_at: '2026-09-08T06:00:00Z',
      device_id: 'device-source',
      server_cursor: 0,
      schema_version: 1,
      note: '',
      operations: [
        {
          client_operation_id: 'imported-1',
          seq: 7,
          entity_type: 'assessment',
          op: 'create',
          status: 'pending',
          created_at: '2026-09-08T06:00:00Z',
          attempt_count: 0,
          last_error: null,
          conflict_detail: null,
          payload: { household_id: 'hh-1', category: 'HOUSE_FULL' },
        },
      ],
    } as never);

    await engine.refreshNow();
    expect(server.assessments.size).toBe(1);
    // The seq was reallocated by this device: a sequence position belongs to one device.
    expect([...server.assessments.values()][0]?.seq).toBe(1);

    await engine.stop();
    await db.close();
  });
});
