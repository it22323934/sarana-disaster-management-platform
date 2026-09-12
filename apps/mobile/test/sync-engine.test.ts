/**
 * The sync engine, driven the way a flood drives it.
 *
 * Every test here is one of the cases file 22 names under "test cases that must exist",
 * plus the ones the server's contract makes possible. The measure of success is never
 * "the call returned"; it is how many assessments are on the server afterwards.
 */

import { describe, expect, it } from 'vitest';

import { AIRPLANE, CAPTIVE_PORTAL, CELLULAR, WIFI } from '../test-support/fakes.js';
import { makeDevice } from '../test-support/harness.js';

describe('a device with no network', () => {
  it('accepts twenty assessments and loses none of them', async () => {
    // The scenario the whole offline core exists for. Airplane mode, twenty assessments,
    // the app killed and reopened, then the network returns.
    const device = await makeDevice({ network: AIRPLANE });
    for (let index = 0; index < 20; index += 1) await device.saveAssessment();

    const offline = await device.engine.request('after-write');
    expect(offline.ran).toBe(false);
    expect(offline.skippedBecause).toBe('offline');
    expect(await device.log.unsyncedCount()).toBe(20);

    // "Killed and reopened": the engine is gone, the database is not.
    device.network.set(WIFI);
    const summary = await device.engine.request('foreground');

    expect(summary.operationsApplied).toBe(20);
    expect(device.server.assessments.size).toBe(20);
    expect(await device.log.unsyncedCount()).toBe(0);
    await device.close();
  });

  it('writes to the device immediately, without waiting for a network', async () => {
    // A GN officer who taps Save and waits for a spinner during a flood has been failed
    // by the design. The row is readable back before anything is sent.
    const device = await makeDevice({ network: AIRPLANE });
    await device.saveAssessment();
    const rows = await device.db.select('SELECT local_id FROM assessment');
    expect(rows).toHaveLength(1);
    await device.close();
  });

  it('sends nothing behind a captive portal', async () => {
    const device = await makeDevice({ network: CAPTIVE_PORTAL });
    await device.saveAssessment();
    expect((await device.engine.request('foreground')).skippedBecause).toBe('offline');
    expect(device.server.pushCalls).toBe(0);
    await device.close();
  });
});

describe('a batch interrupted in flight', () => {
  it('produces no duplicates when the response is lost and the batch is resent', async () => {
    // The case `client_operation_id` exists for. The server applied all twenty; the
    // response never arrived; the device retries the whole batch.
    const device = await makeDevice();
    for (let index = 0; index < 20; index += 1) await device.saveAssessment();

    device.server.failNextPushAfterApply = true;
    const first = await device.engine.request('manual');
    expect(first.error).toMatch(/response was in flight/);
    expect(device.server.assessments.size).toBe(20);
    // Locally nothing is confirmed yet, so all twenty are still unsynced work.
    expect(await device.log.unsyncedCount()).toBe(20);

    const second = await device.engine.refreshNow();
    expect(second.error).toBeNull();
    expect(device.server.assessments.size).toBe(20);
    expect(await device.log.unsyncedCount()).toBe(0);
    await device.close();
  });

  it('returns the whole batch to the queue when the request never leaves', async () => {
    const device = await makeDevice();
    for (let index = 0; index < 5; index += 1) await device.saveAssessment();

    device.server.failNextPushBeforeApply = true;
    await device.engine.request('manual');
    expect(device.server.assessments.size).toBe(0);

    const rows = await device.log.all();
    expect(rows.every((row) => row.status === 'pending')).toBe(true);
    expect(rows.every((row) => row.last_error !== null)).toBe(true);
    await device.close();
  });

  it('resumes across several batches without gaps or duplicates', async () => {
    // Two days offline is more than one batch. Stopping after the first would mean the
    // officer has to trigger the sync by hand once per fifty assessments.
    const device = await makeDevice({ batchSize: 7 });
    for (let index = 0; index < 30; index += 1) await device.saveAssessment();

    const summary = await device.engine.request('foreground');
    expect(summary.operationsSent).toBe(30);
    expect(device.server.assessments.size).toBe(30);

    const seqs = [...device.server.assessments.values()].map((entry) => entry.seq).sort((a, b) => a - b);
    expect(seqs).toEqual(Array.from({ length: 30 }, (_, index) => index + 1));
    await device.close();
  });
});

describe('a gap in the device log', () => {
  it('pauses and reports the missing seq rather than applying out of order', async () => {
    const device = await makeDevice();
    await device.saveAssessment();
    await device.saveAssessment();
    await device.saveAssessment();

    const rows = await device.log.all();
    await device.db.execute('DELETE FROM operation_log WHERE client_operation_id = ?', [
      rows[1]!.client_operation_id,
    ]);

    const summary = await device.engine.request('manual');
    expect(summary.missingSeq).toBe(2);
    expect(summary.operationsSent).toBe(1);
    // Seq 3 stays on the device. Applying it would rebuild a record from an update whose
    // create never arrived.
    expect(device.server.assessments.size).toBe(1);
    expect((await device.log.device()).blocked_on_seq).toBe(2);
    await device.close();
  });
});

describe('a conflict', () => {
  it('jams the queue deliberately, and says so', async () => {
    // The server's cursor is ahead of this device's log, which is what a restored backup
    // looks like. Nothing is merged; the row waits for a person and everything behind it
    // waits with it.
    const device = await makeDevice();
    device.server.cursors.set('device-kandy-01', 5);

    await device.saveAssessment();
    await device.saveAssessment();

    await device.engine.request('manual');

    const rows = await device.log.all();
    expect(rows[0]?.status).toBe('conflict');
    expect(rows[0]?.conflict_detail).toContain('seq_already_consumed');
    expect(await device.log.attentionCount()).toBe(2);

    // A second attempt does not quietly apply anything.
    await device.engine.refreshNow();
    expect(device.server.assessments.size).toBe(0);
    await device.close();
  });
});

describe('media', () => {
  const photo = {
    kind: 'photo' as const,
    local_uri: 'file:///data/sarana/photo-1.jpg',
    content_type: 'image/jpeg',
    size_bytes: 1_400_000,
    entity_type: 'assessment',
  };

  it('sends the assessment before the photograph', async () => {
    // A 4MB photo on a 2G link must not hold up a 200-byte record. The reviewer sees the
    // assessment within seconds and the evidence arrives behind it.
    const device = await makeDevice();
    const operationId = await device.saveAssessment();
    await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
    });

    const summary = await device.engine.request('manual');
    expect(summary.operationsApplied).toBe(1);
    expect(summary.mediaUploaded).toBe(1);
    expect(device.server.media.size).toBe(1);
    await device.close();
  });

  it('holds a photograph whose record has not synced yet', async () => {
    // There is nothing on the server to attach it to. This is the ordering working, not
    // a failure, so nothing is marked failed.
    const device = await makeDevice({ network: AIRPLANE });
    const operationId = await device.saveAssessment();
    await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
    });

    device.network.set(CELLULAR);
    await device.engine.request('manual');
    expect((await device.media.counts()).failed).toBe(0);
    await device.close();
  });

  it('defers a photograph on a metered link and sends it when Wi-Fi appears', async () => {
    const device = await makeDevice({ network: CELLULAR });
    const operationId = await device.saveAssessment();
    await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
    });

    await device.engine.request('manual');
    expect(device.server.assessments.size).toBe(1);
    expect(device.server.media.size).toBe(0);
    expect((await device.media.counts()).deferred).toBe(1);

    device.network.set(WIFI);
    await device.engine.refreshNow();
    expect(device.server.media.size).toBe(1);
    await device.close();
  });

  it('sends an urgent photograph over a metered link', async () => {
    const device = await makeDevice({ network: CELLULAR });
    const operationId = await device.saveAssessment();
    await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
      urgent: true,
    });

    await device.engine.request('manual');
    expect(device.server.media.size).toBe(1);
    await device.close();
  });

  it('resumes an interrupted upload from where it stopped', async () => {
    const device = await makeDevice();
    const operationId = await device.saveAssessment();
    const item = await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
    });

    device.server.interruptUploadAfter = 900_000;
    await device.engine.request('manual');
    expect((await device.media.byId(item.id))?.bytes_sent).toBe(900_000);
    expect(device.server.media.size).toBe(0);

    await device.engine.refreshNow();
    expect(device.server.media.size).toBe(1);
    await device.close();
  });

  it('does not fail the run when a photograph fails', async () => {
    // The text is already away, which is the half that matters. The photo retries on the
    // next trigger rather than dragging the assessment back into the queue.
    const device = await makeDevice();
    const operationId = await device.saveAssessment();
    await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
    });

    device.server.failNextMediaUpload = true;
    const summary = await device.engine.request('manual');
    expect(summary.error).toBeNull();
    expect(summary.operationsApplied).toBe(1);
    expect(summary.mediaUploaded).toBe(0);
    await device.close();
  });

  it('never retries a photograph the server refused', async () => {
    // Too large, or a type that is not accepted. Retrying sends the same file to the same
    // rule; it is surfaced instead.
    const device = await makeDevice();
    const operationId = await device.saveAssessment();
    const item = await device.media.enqueue({
      ...photo,
      client_operation_id: operationId,
      entity_local_id: 'asm_local_1',
      size_bytes: 9_000_000,
    });

    device.server.refuseNextMedia = true;
    await device.engine.request('manual');
    expect((await device.media.byId(item.id))?.status).toBe('refused');

    await device.engine.refreshNow();
    expect(device.server.media.size).toBe(0);
    expect((await device.media.counts()).failed).toBe(1);
    await device.close();
  });
});

describe('triggers', () => {
  it('runs one sync at a time and does not drop the second request', async () => {
    // A foreground event and a connectivity change land within milliseconds of each other
    // on a real handset. Racing them would send one batch twice.
    const device = await makeDevice();
    await device.saveAssessment();

    const [first, second] = await Promise.all([
      device.engine.request('foreground'),
      device.engine.request('connectivity'),
    ]);

    const ranCount = [first, second].filter((summary) => summary.ran).length;
    expect(ranCount).toBe(1);
    expect(device.server.assessments.size).toBe(1);
    await device.close();
  });

  it('syncs as soon as connectivity returns, without waiting for the backoff', async () => {
    const device = await makeDevice({ network: AIRPLANE });
    await device.engine.start();
    await device.saveAssessment();
    await device.engine.request('after-write');

    device.network.set(WIFI);
    // `start` wired the change to a sync; give the microtask queue a turn to run it.
    await new Promise((resolve) => setImmediate(resolve));
    expect(device.server.assessments.size).toBe(1);
    await device.close();
  });

  it('holds back an automatic retry after a failure, but not a pull-to-refresh', async () => {
    const device = await makeDevice();
    await device.saveAssessment();

    device.server.failNextPushBeforeApply = true;
    await device.engine.request('background-task');

    expect((await device.engine.request('background-task')).skippedBecause).toBe('backoff');
    // The user has walked to the top of the hill. They know something the app cannot.
    expect((await device.engine.refreshNow()).ran).toBe(true);
    expect(device.server.assessments.size).toBe(1);
    await device.close();
  });

  it('reports progress as a fraction of the run, not of what is left', async () => {
    const device = await makeDevice({ batchSize: 5 });
    for (let index = 0; index < 5; index += 1) await device.saveAssessment();

    const seen: Array<{ done: number; total: number }> = [];
    const unsubscribe = device.engine.subscribe((state) => {
      if (state.progress) seen.push(state.progress);
    });
    await device.engine.request('manual');
    unsubscribe();

    expect(seen[0]).toEqual({ done: 0, total: 5 });
    expect(seen.at(-1)).toEqual({ done: 5, total: 5 });
    await device.close();
  });
});

describe('citizen reports', () => {
  it('submits them one at a time, not through the assessment batch endpoint', async () => {
    // A report can become a dispatch. A batch endpoint that half-succeeds would be a
    // dispatcher's problem rather than a device's.
    const device = await makeDevice();
    await device.log.append({
      entity_type: 'report',
      entity_local_id: 'rep_local_1',
      op: 'create',
      payload: { text: 'Water in the house, three people upstairs', language: 'si', channel: 'APP' },
    });

    await device.engine.request('manual');
    expect(device.server.reportCalls).toBe(1);
    expect(device.server.pushCalls).toBe(0);
    expect((await device.log.all())[0]?.server_id).toBe('rep_1');
    await device.close();
  });
});
