/**
 * The queue export.
 *
 * The file that makes "never log a user out while unsynced operations exist" survivable.
 * Two properties matter: it is complete, and it carries no credential.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { migrate, SCHEMA_VERSION } from '../src/offline/db/schema.js';
import type { Database } from '../src/offline/db/types.js';
import { exportQueue } from '../src/offline/export.js';
import { OperationLog } from '../src/offline/log/operation-log.js';
import { TestClock } from '../test-support/fakes.js';
import { openTestDatabase } from '../test-support/node-database.js';

let db: Database;
let log: OperationLog;

beforeEach(async () => {
  db = openTestDatabase();
  await migrate(db);
  log = new OperationLog(db, new TestClock());
  await log.register('device-kandy-01');
});

afterEach(async () => {
  await db.close();
});

async function append(household: string) {
  return log.append({
    entity_type: 'assessment',
    entity_local_id: household,
    op: 'create',
    payload: { household_id: household, category: 'HOUSE_PARTIAL' },
  });
}

describe('exportQueue', () => {
  it('carries every unsynced operation and none of the confirmed ones', async () => {
    const first = await append('hh-1');
    await append('hh-2');
    await log.applyResults([
      { client_operation_id: first.client_operation_id, status: 'applied', server_id: 'srv-1' },
    ]);

    const payload = await exportQueue(log);
    expect(payload.operations).toHaveLength(1);
    expect(payload.operations[0]).toMatchObject({ seq: 2, entity_type: 'assessment' });
  });

  it('carries the idempotency keys, because they are what make a replay safe', async () => {
    const record = await append('hh-1');
    const payload = await exportQueue(log);
    expect(payload.operations[0]).toMatchObject({
      client_operation_id: record.client_operation_id,
    });
    expect(payload.note).toContain('client_operation_id');
  });

  it('carries the device id, the cursor and the schema version', async () => {
    // Everything the district office needs to replay the log by hand against the server.
    await append('hh-1');
    const payload = await exportQueue(log);
    expect(payload.device_id).toBe('device-kandy-01');
    expect(payload.server_cursor).toBe(0);
    expect(payload.schema_version).toBe(SCHEMA_VERSION);
  });

  it('marks an unreadable payload rather than dropping it', async () => {
    // The whole point of the file is that it is a complete account of what is on the
    // device. Quietly skipping the one row that will not parse makes it a misleading one.
    const record = await append('hh-1');
    await db.execute('UPDATE operation_log SET payload = ? WHERE client_operation_id = ?', [
      '{broken',
      record.client_operation_id,
    ]);
    const payload = await exportQueue(log);
    expect(payload.operations[0]?.payload).toEqual({ unreadable: true, raw: '{broken' });
  });

  it('contains no token, key or session', async () => {
    // The file is handed to someone else. Anything credential-shaped in it is a
    // credential that has left the keystore.
    await append('hh-1');
    const serialised = JSON.stringify(await exportQueue(log)).toLowerCase();
    for (const forbidden of ['access_token', 'refresh_token', 'capability_token', 'bearer']) {
      expect(serialised).not.toContain(forbidden);
    }
  });
});
