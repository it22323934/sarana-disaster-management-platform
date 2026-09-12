/**
 * Exporting the queue.
 *
 * The escape hatch behind "never log a user out while unsynced operations exist". A
 * device that has to be wiped, reassigned or carried to the district office hands over a
 * file instead of losing the work.
 *
 * The file contains the operations and nothing else: no token, no database key, no
 * session. `export-file.ts` writes it to the app's document directory; that half is
 * separated so this one, which decides what goes in, can be tested without a device.
 */

import { EXPORT_NOTE, type QueueExport } from '../auth/logout.js';
import { SCHEMA_VERSION } from './db/schema.js';
import type { OperationLog } from './log/operation-log.js';
import { payloadOf } from './log/types.js';

/**
 * Everything the server has not confirmed, in sequence order.
 *
 * A corrupt payload is exported as a marker rather than skipped. The whole point of the
 * file is that it is a complete account of what is on the device; quietly dropping the
 * one row that will not parse would make it a misleading one.
 */
export async function exportQueue(log: OperationLog): Promise<QueueExport> {
  const device = await log.device();
  const records = (await log.all()).filter((record) => record.status !== 'synced');

  return {
    exported_at: new Date().toISOString(),
    device_id: device.device_id,
    server_cursor: device.server_cursor,
    schema_version: SCHEMA_VERSION,
    operations: records.map((record) => {
      let payload: unknown;
      try {
        payload = payloadOf(record);
      } catch {
        payload = { unreadable: true, raw: record.payload };
      }
      return {
        client_operation_id: record.client_operation_id,
        seq: record.seq,
        entity_type: record.entity_type,
        op: record.op,
        status: record.status,
        created_at: record.created_at,
        attempt_count: record.attempt_count,
        last_error: record.last_error,
        conflict_detail: record.conflict_detail,
        payload,
      };
    }),
    note: EXPORT_NOTE,
  };
}
