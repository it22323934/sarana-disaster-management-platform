/**
 * How much room is left, and what to do about it.
 *
 * `assessStorage` decides; this reads. The split is so the thresholds - warn at 200MB,
 * refuse a photo at 50MB - are tested without a device, and this file has nothing in it
 * that can be wrong except the platform call.
 */

import * as FileSystem from 'expo-file-system';

import { overrides } from '../../debug/bridge.js';
import { assessStorage, type StorageVerdict } from './guard.js';
import type { MediaQueue } from '../media/queue.js';

/**
 * Free bytes on the volume the app writes to.
 *
 * Returns `Number.MAX_SAFE_INTEGER` if the platform will not say. Refusing every photo
 * because a call failed would be worse than the problem: an officer with a working
 * device and no way to attach evidence.
 */
export async function freeBytes(): Promise<number> {
  if (overrides.freeBytes !== null) return overrides.freeBytes;
  try {
    return await FileSystem.getFreeDiskStorageAsync();
  } catch {
    return Number.MAX_SAFE_INTEGER;
  }
}

/** The verdict, for the capture button and the storage warning. */
export async function storageVerdict(media: MediaQueue): Promise<StorageVerdict> {
  return assessStorage({
    freeBytes: await freeBytes(),
    mediaCacheBytes: await media.cacheBytes(),
  });
}

/**
 * Delete the files behind evicted media rows.
 *
 * `MediaQueue.evict` decides which rows go and removes them from the database; the files
 * are removed here, because file removal is a platform call and the queue owns only the
 * database. A file that fails to delete is left alone: the row is already gone, so the
 * worst case is an orphaned file the next eviction pass will not find, which is a smaller
 * problem than an exception in the middle of freeing space.
 */
export async function reclaimSpace(media: MediaQueue): Promise<{ freed: number; stillOver: boolean }> {
  const { removed, stillOver } = await media.evict();
  let freed = 0;
  for (const item of removed) {
    try {
      new FileSystem.File(item.local_uri).delete();
      freed += item.size_bytes;
    } catch {
      // Already gone, or on a volume that was unmounted. Nothing to do about it here.
    }
  }
  return { freed, stillOver };
}
