/**
 * The fifteen-minute background sync.
 *
 * One of five triggers, and the least reliable of them by design: both platforms treat a
 * background task as a request, not a promise, and Android's Doze will skip it for hours
 * on a device in a pocket. Nothing depends on it. It exists so a phone left on a table
 * in an evacuation centre catches up without anyone touching it, and the status strip
 * tells the truth either way.
 *
 * The handler is registered at module scope because `TaskManager` requires it to be
 * defined before the JS context finishes loading - a task that fires while the app is
 * terminated has no component tree to hang it off.
 */

import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';

import type { SyncEngine } from './engine.js';

export const BACKGROUND_SYNC_TASK = 'sarana.sync.background';

/** Fifteen minutes, from the brief. The OS treats it as a floor, never a guarantee. */
export const BACKGROUND_INTERVAL_MINUTES = 15;

/**
 * The engine the background handler reaches for.
 *
 * A module-level reference, which is the shape the platform forces: the task fires
 * outside React, so there is no context to read. It is null until the app has opened
 * once and built one, and the handler says so rather than throwing into a log nobody
 * reads.
 */
let engine: SyncEngine | null = null;

export function setEngineForBackgroundSync(instance: SyncEngine | null): void {
  engine = instance;
}

TaskManager.defineTask(BACKGROUND_SYNC_TASK, async () => {
  if (!engine) return BackgroundTask.BackgroundTaskResult.Failed;
  const summary = await engine.request('background-task');
  // `Success` means "this was worth waking me for", which is what the scheduler uses to
  // decide how often to wake us again. A run that found nothing to send is honestly
  // reported as such, so a device with no work stops being woken.
  return summary.operationsSent > 0 || summary.mediaUploaded > 0
    ? BackgroundTask.BackgroundTaskResult.Success
    : BackgroundTask.BackgroundTaskResult.Failed;
});

export async function registerBackgroundSync(): Promise<boolean> {
  const status = await BackgroundTask.getStatusAsync();
  if (status === BackgroundTask.BackgroundTaskStatus.Restricted) {
    // Low Power Mode on iOS, or Background App Refresh switched off. Not an error, and
    // not something to nag about: the other four triggers still work.
    return false;
  }

  await BackgroundTask.registerTaskAsync(BACKGROUND_SYNC_TASK, {
    minimumInterval: BACKGROUND_INTERVAL_MINUTES,
  });
  return true;
}

export async function unregisterBackgroundSync(): Promise<void> {
  if (await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK)) {
    await BackgroundTask.unregisterTaskAsync(BACKGROUND_SYNC_TASK);
  }
}
