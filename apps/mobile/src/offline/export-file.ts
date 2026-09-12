/**
 * Writing the queue export to a file.
 *
 * Kept apart from `export.ts` so the part that decides *what* is in the file can be
 * tested without a device. This half is one platform call and has nothing to decide.
 */

import * as FileSystem from 'expo-file-system';

import type { QueueExport } from '../auth/logout.js';

/** Write the export and return the path. The caller shares it. */
export async function writeQueueExport(payload: QueueExport): Promise<string> {
  const stamp = payload.exported_at.replace(/[:.]/g, '-');
  const file = new FileSystem.File(
    FileSystem.Paths.document,
    `sarana-queue-${payload.device_id}-${stamp}.json`,
  );
  file.create({ overwrite: true });
  file.write(JSON.stringify(payload, null, 2));
  return file.uri;
}
