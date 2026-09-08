/**
 * The operation log, against a real SQLite engine.
 *
 * The migrations, the CHECK constraints and the SQL are the ones that ship. What these
 * tests cannot see is SQLCipher and the JSI bridge; everything above them is identical to
 * a handset.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { migrate, SCHEMA_VERSION } from '../src/offline/db/schema.js';
import { OperationLog } from '../src/offline/log/operation-log.js';
import { CorruptPayloadError, payloadOf } from '../src/offline/log/types.js';
import type { Database } from '../src/offline/db/types.js';
import { TestClock } from '../test-support/fakes.js';
import { openTestDatabase } from '../test-support/node-database.js';

let db: Database;
let clock: TestClock;
let log: OperationLog;

beforeEach(async () => {
  db = openTestDatabase();
  await migrate(db);
  clock = new TestClock();
  log = new OperationLog(db, clock);
  await log.register('device-kandy-01');
});

afterEach(async () => {
  await db.close();
});

const draft = { household_id: 'hh-1', category: 'HOUSE_PARTIAL', cost_estimate_lkr_cents: 1000 };

async function append(localId: string) {
  return log.append({
    entity_type: 'assessment',
    entity_local_id: localId,
    op: 'create',
    payload: draft,
  });
}

describe('migrations', () => {
  it('stamps the schema version so a device upgraded later runs only what it has not', async () => {
    const [row] = await db.select<{ user_version: number }>('PRAGMA user_version');
    expect(row?.user_version).toBe(SCHEMA_VERSION);
  });

  it('is safe to run twice', async () => {
    await expect(migrate(db)).resolves.toBe(SCHEMA_VERSION);
  });

  it('refuses a status the sync contract does not have a name for', async () => {
    // The CHECK constraint is the last line of defence for the one vocabulary the device
    // and the server have to agree on.
    await expect(
      db.execute(
        "INSERT INTO operation_log (client_operation_id, seq, entity_type, entity_local_id, " +
          "op, payload, created_at, status) VALUES ('x', 1, 'assessment', 'a', 'create', " +
          "'{}', '2026-09-08T00:00:00Z', 'nearly-done')",
      ),
    ).rejects.toThrow();
  });
});

describe('append', () => {
  it('numbers operations from one, in order', async () => {
    expect((await append('a')).seq).toBe(1);
    expect((await append('b')).seq).toBe(2);
    expect((await append('c')).seq).toBe(3);
  });

  it('starts every operation pending, with no attempts', async () => {
    const record = await append('a');
    expect(record.status).toBe('pending');
    expect(record.attempt_count).toBe(0);
    expect(record.synced_at).toBeNull();
    expect(record.server_id).toBeNull();
  });

  it('writes the entity row in the same transaction as the operation', async () => {
    // The pairing is the guarantee. A device holding an assessment with no operation has
    // work it will never sync and no way to know.
    await log.append(
      { entity_type: 'assessment', entity_local_id: 'asm-1', op: 'create', payload: draft },
      async (tx) => {
        await tx.execute(
          'INSERT INTO assessment (local_id, household_id, gn_division_id, gn_division_code, ' +
            'hazard_event_id, category, cost_estimate_lkr_cents, assessed_at, status, updated_at) ' +
            "VALUES ('asm-1', 'hh-1', 'gn-1', 'LK-2-05-020-1015', 'hz-1', 'HOUSE_PARTIAL', " +
            "1000, '2026-09-08T06:00:00Z', 'SUBMITTED', '2026-09-08T06:00:00Z')",
        );
      },
    );
    const rows = await db.select('SELECT local_id FROM assessment');
    expect(rows).toHaveLength(1);
  });

  it('appends nothing when the entity write fails', async () => {
    await expect(
      log.append(
        { entity_type: 'assessment', entity_local_id: 'asm-1', op: 'create', payload: draft },
        async () => {
          throw new Error('disk full');
        },
      ),
    ).rejects.toThrow('disk full');

    expect(await log.all()).toHaveLength(0);
    // And the sequence did not advance, so the next write is still seq 1 rather than
    // leaving a hole the server would pause on.
    expect((await log.device()).next_seq).toBe(1);
  });

  it('never reuses a sequence number, even after the log is purged', async () => {
    // A purged log restarting at 1 would look to the server like a device replaying a log
    // it should have discarded, and every operation would come back as a conflict.
    await append('a');
    await append('b');
    await log.applyResults([
      { client_operation_id: (await log.all())[0]!.client_operation_id, status: 'applied' },
      { client_operation_id: (await log.all())[1]!.client_operation_id, status: 'applied' },
    ]);
    clock.advance(40 * 86_400_000);
    expect(await log.purgeSynced()).toBe(2);
    expect(await log.all()).toHaveLength(0);
    expect((await append('c')).seq).toBe(3);
  });
});

describe('claim', () => {
  it('marks a batch in flight and counts the attempt', async () => {
    await append('a');
    await append('b');
    const plan = await log.claim();
    expect(plan.operations).toHaveLength(2);
    const rows = await log.all();
    expect(rows.every((row) => row.status === 'syncing')).toBe(true);
    expect(rows.every((row) => row.attempt_count === 1)).toBe(true);
  });

  it('does not hand the same operation to two callers', async () => {
    // A foreground event and a connectivity change land within milliseconds of each other
    // on a real handset. Both would otherwise carry the same batch.
    await append('a');
    const first = await log.claim();
    const second = await log.claim();
    expect(first.operations).toHaveLength(1);
    expect(second.operations).toHaveLength(0);
  });

  it('respects the batch size', async () => {
    for (let index = 0; index < 12; index += 1) await append(`a${index}`);
    expect((await log.claim(5)).operations).toHaveLength(5);
  });

  it('records a gap on the device row so the strip can report it', async () => {
    await append('a');
    await append('b');
    await append('c');
    // Delete the middle operation, which is what a partial restore or a corrupted page
    // produces. The device must stop, not skip.
    const rows = await log.all();
    await db.execute('DELETE FROM operation_log WHERE client_operation_id = ?', [
      rows[1]!.client_operation_id,
    ]);
    const plan = await log.claim();
    expect(plan.operations.map((record) => record.seq)).toEqual([1]);
    expect(plan.missingSeq).toBe(2);
    expect((await log.device()).blocked_on_seq).toBe(2);
  });
});

describe('release', () => {
  it('returns a batch to pending after a transport failure', async () => {
    await append('a');
    const plan = await log.claim();
    await log.release(
      plan.operations.map((record) => record.client_operation_id),
      { error: 'the connection dropped' },
    );
    const [row] = await log.all();
    expect(row?.status).toBe('pending');
    expect(row?.last_error).toBe('the connection dropped');
  });

  it('gives up only after enough attempts to mean something', async () => {
    // A device in a valley fails every attempt, and none of those is a problem the
    // officer can do anything about. Marking it failed on the first try would fill the
    // attention count with weather.
    await append('a');
    for (let attempt = 1; attempt <= 4; attempt += 1) {
      const plan = await log.claim();
      await log.release(
        plan.operations.map((record) => record.client_operation_id),
        { error: 'no signal', failAfter: 5 },
      );
      expect((await log.all())[0]?.status).toBe('pending');
    }
    const plan = await log.claim();
    await log.release(
      plan.operations.map((record) => record.client_operation_id),
      { error: 'no signal', failAfter: 5 },
    );
    expect((await log.all())[0]?.status).toBe('failed');
  });
});

describe('applyResults', () => {
  it('treats a duplicate as a success, because it is one', async () => {
    // It is the device learning about a confirmation that never made it back over the
    // network the first time.
    const record = await append('a');
    await log.applyResults([
      { client_operation_id: record.client_operation_id, status: 'duplicate', server_id: 'srv-1' },
    ]);
    const [row] = await log.all();
    expect(row?.status).toBe('synced');
    expect(row?.server_id).toBe('srv-1');
  });

  it('keeps a conflict for a person and never merges it', async () => {
    const record = await append('a');
    await log.applyResults([
      {
        client_operation_id: record.client_operation_id,
        status: 'conflict',
        conflict: { reason: 'seq_already_consumed', seq: 1 },
        detail: 'this needs a person to look at the device log',
      },
    ]);
    const [row] = await log.all();
    expect(row?.status).toBe('conflict');
    expect(row?.conflict_detail).toBe('{"reason":"seq_already_consumed","seq":1}');
    expect(await log.attentionCount()).toBe(1);
  });

  it('holds a blocked operation without calling it an error', async () => {
    const record = await append('a');
    await log.applyResults([
      { client_operation_id: record.client_operation_id, status: 'blocked', detail: 'held' },
    ]);
    expect((await log.all())[0]?.status).toBe('blocked');
    // Blocked is unsynced work, not work that needs a person: the gap in front of it may
    // fill on the next batch.
    expect(await log.attentionCount()).toBe(0);
    expect(await log.unsyncedCount()).toBe(1);
  });
});

describe('purgeSynced', () => {
  it('keeps everything the server has not confirmed, however old', async () => {
    // The log is never truncated until the server confirms. A device wiped between sync
    // and confirmation loses data, so confirmation is what triggers cleanup.
    await append('a');
    clock.advance(400 * 86_400_000);
    expect(await log.purgeSynced()).toBe(0);
    expect(await log.all()).toHaveLength(1);
  });

  it('keeps a recently confirmed operation even if the write is old', async () => {
    const record = await append('a');
    clock.advance(90 * 86_400_000);
    await log.applyResults([{ client_operation_id: record.client_operation_id, status: 'applied' }]);
    expect(await log.purgeSynced()).toBe(0);
  });

  it('drops confirmed operations after thirty days', async () => {
    const record = await append('a');
    await log.applyResults([{ client_operation_id: record.client_operation_id, status: 'applied' }]);
    clock.advance(31 * 86_400_000);
    expect(await log.purgeSynced()).toBe(1);
  });
});

describe('payloadOf', () => {
  it('reads the payload back', async () => {
    expect(payloadOf(await append('a'))).toEqual(draft);
  });

  it('names the operation when a payload cannot be read', async () => {
    // A row that cannot be sent and cannot be repaired on the device. The message says to
    // export the log rather than suggesting a retry that will never work.
    const record = await append('a');
    await db.execute('UPDATE operation_log SET payload = ? WHERE client_operation_id = ?', [
      '{not json',
      record.client_operation_id,
    ]);
    const corrupt = (await log.all())[0]!;
    expect(() => payloadOf(corrupt)).toThrow(CorruptPayloadError);
    expect(() => payloadOf(corrupt)).toThrow(record.client_operation_id);
  });
});
