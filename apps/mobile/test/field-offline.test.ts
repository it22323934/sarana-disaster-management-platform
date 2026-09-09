/**
 * A day of fieldwork with no signal, and everything reaching the server exactly once.
 * `pnpm --filter mobile test -- field`
 *
 * The brief's first test case, and the highest-stakes one in the project: "40 assessments
 * with 80 photos created across a 6-hour airplane-mode session, app killed twice, then
 * reconnected: all 40 sync exactly once, all 80 photos arrive, correctly linked."
 *
 * A duplicate here is two payments against one household. A loss is none. Both are
 * findings an auditor would raise about the officer, which is the framing the brief asks
 * for: this record is the officer's evidence, and it has to survive the day they had.
 *
 * The app being "killed" is modelled by closing the database handle and reopening it
 * against the same file, which is what a process kill leaves behind. Nothing is held in
 * memory across the boundary: if a queued write lived only in a JavaScript array, it would
 * not survive here and it would not survive on the handset.
 */

import { describe, expect, it } from 'vitest';

import { migrate } from '../src/offline/db/schema.js';
import { MediaQueue } from '../src/offline/media/queue.js';
import { OperationLog } from '../src/offline/log/operation-log.js';
import { SyncEngine } from '../src/offline/sync/engine.js';
import { calculate, type CostSchedule } from '../src/field/entitlement.js';
import { saveFieldAssessment, type AssessmentPhoto } from '../src/field/save-assessment.js';
import { AIRPLANE, FakeNetwork, FakeServer, TestClock, WIFI } from '../test-support/fakes.js';
import { openTestDatabase } from '../test-support/node-database.js';
import type { Database } from '../src/offline/db/types.js';

const SCHEDULE: CostSchedule = {
  version: '2026-03',
  household_cap_cents: 400_000_00,
  lines: {
    HOUSE_PARTIAL: {
      line_id: 'line-hp',
      category: 'HOUSE_PARTIAL',
      unit_amount_cents: 75_000_00,
      max_units: 1,
      formula: 'house_partial * 75000',
    },
    HOUSEHOLD_GOODS: {
      line_id: 'line-hg',
      category: 'HOUSEHOLD_GOODS',
      unit_amount_cents: 25_000_00,
      max_units: 2,
      formula: 'household_goods * 25000',
    },
  },
};

function photos(index: number): AssessmentPhoto[] {
  return [
    {
      localUri: `file:///data/photos/${index}-wide.jpg`,
      contentType: 'image/jpeg',
      sizeBytes: 1_400_000,
      latitude: 7.2906,
      longitude: 80.6337,
      perceptualHash: `phash-${index}-wide`,
      kind: 'wide',
    },
    {
      localUri: `file:///data/photos/${index}-detail.jpg`,
      contentType: 'image/jpeg',
      sizeBytes: 900_000,
      latitude: 7.2906,
      longitude: 80.6337,
      perceptualHash: `phash-${index}-detail`,
      kind: 'detail',
    },
  ];
}

/**
 * One handset, opened and closed the way a process kill opens and closes it.
 *
 * The file path is shared across reopenings; only the JavaScript objects are new. That is
 * the whole point of the exercise — anything the device "remembers" has to be in SQLite.
 */
function openHandset(path: string) {
  const db = openTestDatabase(path);
  return db;
}

async function wire(db: Database, clock: TestClock, server: FakeServer, network: FakeNetwork) {
  const log = new OperationLog(db, clock);
  const media = new MediaQueue(db, clock);
  const engine = new SyncEngine({
    log,
    media,
    transport: server,
    network,
    clock,
    batchSize: 50,
    backoff: { random: () => 0.5 },
  });
  return { log, media, engine };
}

describe('a six-hour airplane-mode session, killed twice', () => {
  it('syncs all 40 assessments exactly once with all 80 photos linked', async () => {
    const path = `field-6h-${Date.now()}`;
    const clock = new TestClock();
    const server = new FakeServer();
    const network = new FakeNetwork(AIRPLANE);

    let db = openHandset(path);
    await migrate(db);
    let { log, media, engine } = await wire(db, clock, server, network);
    await log.register('device-kandy-01');

    const saved: string[] = [];

    // Six hours, forty assessments, two photographs each. The officer walks the division;
    // the phone never sees a tower.
    for (let index = 0; index < 40; index += 1) {
      const result = await saveFieldAssessment(
        { log, media, schedule: SCHEDULE },
        {
          householdId: `018f4a2b-0000-7000-8000-${String(index).padStart(12, '0')}`,
          householdLocalId: `hh_local_${index}`,
          gnDivisionId: '018f4a2b-0000-7000-8000-000000000002',
          gnDivisionCode: 'LK-2-05-020-1015',
          hazardEventId: '018f4a2b-0000-7000-8000-000000000003',
          items: [
            { category: 'HOUSE_PARTIAL', units: 1 },
            { category: 'HOUSEHOLD_GOODS', units: 1 },
          ],
          photos: photos(index),
          latitude: 7.2906,
          longitude: 80.6337,
          gpsAccuracyM: 12,
          locationSource: 'GPS',
          source: 'PHONE',
        },
        { now: clock.now() },
      );
      saved.push(result.clientOperationId);

      // Roughly nine minutes per household including the walk between them: six hours of
      // work, which is what the brief describes.
      clock.advance(9 * 60_000);

      // The app is killed twice during the session — once early, once late. On a
      // mid-range Android running a camera for six hours this is not a hypothetical.
      if (index === 12 || index === 31) {
        await engine.stop();
        await db.close();
        db = openHandset(path);
        await migrate(db);
        ({ log, media, engine } = await wire(db, clock, server, network));
      }
    }

    expect(saved).toHaveLength(40);
    expect(new Set(saved).size).toBe(40);

    // Nothing left the device: the whole session was offline.
    expect(server.assessments.size).toBe(0);

    // The officer reaches a town with a signal and leaves the phone on the desk.
    network.set(WIFI);

    // **The photos need more than one run, and that is the design rather than a
    // limitation.** The engine uploads a bounded number of media items per run so a 4MB
    // photograph cannot monopolise the link while a 200-byte assessment waits behind it.
    // A real device syncs on a fifteen-minute background task and on every connectivity
    // change; this loop is that, compressed.
    //
    // The bound is asserted rather than assumed: if the queue ever stalls instead of
    // draining, this fails with the count it reached rather than looping forever.
    let runs = 0;
    for (; runs < 60; runs += 1) {
      await engine.refreshNow();
      const counts = await media.counts();
      if (counts.pending === 0 && counts.deferred === 0 && counts.uploading === 0) break;
    }
    expect(runs, 'the media queue did not drain within sixty sync runs').toBeLessThan(60);

    // The text arrived first and in one run, which is the half a reviewer needs
    // immediately. The photographs followed behind it.
    expect(server.assessments.size).toBe(40);

    // Exactly once. Every stored assessment is one of the forty the device minted, and no
    // client operation id appears twice — which is what stops one household being paid
    // for the same damage twice.
    const storedIds = [...server.assessments.values()].map((entry) => entry.clientOperationId);
    expect(new Set(storedIds).size).toBe(40);
    expect(storedIds.every((id) => saved.includes(id))).toBe(true);

    // All eighty photographs arrived, and each is linked to the operation that explains it.
    expect(server.media.size).toBe(80);

    const uploaded = await db.select<{ client_operation_id: string; status: string }>(
      'SELECT client_operation_id, status FROM media_upload',
    );
    expect(uploaded).toHaveLength(80);
    expect(uploaded.every((row) => row.status === 'uploaded')).toBe(true);
    // Two per assessment, none orphaned onto an operation that was never saved.
    for (const clientOperationId of saved) {
      expect(uploaded.filter((row) => row.client_operation_id === clientOperationId)).toHaveLength(2);
    }

    await engine.stop();
    await db.close();
  }, 60_000);
});

describe('the record the officer is left holding', () => {
  it('keeps the line items, the provisional figure and its working', async () => {
    const path = `field-record-${Date.now()}`;
    const clock = new TestClock();
    const db = openHandset(path);
    await migrate(db);
    const { log, media, engine } = await wire(db, clock, new FakeServer(), new FakeNetwork(AIRPLANE));
    await log.register('device-kandy-02');

    const result = await saveFieldAssessment(
      { log, media, schedule: SCHEDULE },
      {
        householdId: '018f4a2b-0000-7000-8000-000000000001',
        householdLocalId: 'hh_local_1',
        gnDivisionId: '018f4a2b-0000-7000-8000-000000000002',
        gnDivisionCode: 'LK-2-05-020-1015',
        hazardEventId: '018f4a2b-0000-7000-8000-000000000003',
        items: [
          { category: 'HOUSE_PARTIAL', units: 1 },
          { category: 'HOUSEHOLD_GOODS', units: 2 },
        ],
        photos: photos(1),
        latitude: 7.2906,
        longitude: 80.6337,
        gpsAccuracyM: 8,
        locationSource: 'GPS',
        source: 'PHONE',
      },
      { now: clock.now() },
    );

    const expected = calculate(
      [
        { category: 'HOUSE_PARTIAL', units: 1 },
        { category: 'HOUSEHOLD_GOODS', units: 2 },
      ],
      SCHEDULE,
    );
    expect(result.provisionalEntitlementCents).toBe(expected.result_lkr_cents);

    const [row] = await db.select<{
      source: string;
      location_source: string;
      provisional_entitlement_cents: number;
      provisional_trace: string;
      cost_schedule_version: string;
      category: string;
    }>('SELECT * FROM assessment WHERE local_id = ?', [result.localId]);

    expect(row?.source).toBe('PHONE');
    expect(row?.location_source).toBe('GPS');
    expect(row?.cost_schedule_version).toBe('2026-03');
    // The working is kept verbatim, so a later disagreement can be traced to what the
    // officer was shown rather than argued about.
    expect(JSON.parse(row!.provisional_trace)).toEqual(expected);

    // Both items are on the device even though the sync payload carries one category.
    const items = await db.select<{ category: string; units: number }>(
      'SELECT category, units FROM assessment_item WHERE assessment_local_id = ? ORDER BY category',
      [result.localId],
    );
    expect(items).toEqual([
      { category: 'HOUSEHOLD_GOODS', units: 2 },
      { category: 'HOUSE_PARTIAL', units: 1 },
    ]);

    // The synced category is the one that dominates the entitlement, not the first typed.
    expect(row?.category).toBe('HOUSE_PARTIAL');

    await engine.stop();
    await db.close();
  });

  it('records a paper transcription as PAPER, with the form photographed', async () => {
    const path = `field-paper-${Date.now()}`;
    const clock = new TestClock();
    const db = openHandset(path);
    await migrate(db);
    const { log, media, engine } = await wire(db, clock, new FakeServer(), new FakeNetwork(AIRPLANE));
    await log.register('device-kandy-03');

    const result = await saveFieldAssessment(
      { log, media, schedule: SCHEDULE },
      {
        householdId: '018f4a2b-0000-7000-8000-000000000001',
        householdLocalId: 'hh_local_1',
        gnDivisionId: '018f4a2b-0000-7000-8000-000000000002',
        gnDivisionCode: 'LK-2-05-020-1015',
        hazardEventId: '018f4a2b-0000-7000-8000-000000000003',
        items: [{ category: 'HOUSE_PARTIAL', units: 1 }],
        photos: [
          ...photos(9),
          {
            localUri: 'file:///data/photos/9-form.jpg',
            contentType: 'image/jpeg',
            sizeBytes: 700_000,
            kind: 'paper-form',
          },
        ],
        latitude: 7.2906,
        longitude: 80.6337,
        gpsAccuracyM: 15,
        locationSource: 'GPS',
        source: 'PAPER',
      },
      { now: clock.now() },
    );

    const [row] = await db.select<{ source: string }>(
      'SELECT source FROM assessment WHERE local_id = ?',
      [result.localId],
    );
    // The audit trail survives the paper stage: the record says it went through paper and
    // the paper itself is attached.
    expect(row?.source).toBe('PAPER');
    expect(result.mediaIds).toHaveLength(3);

    await engine.stop();
    await db.close();
  });
});
