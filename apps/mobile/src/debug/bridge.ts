/**
 * The debug bridge the offline e2e suite drives the device through.
 *
 * Every action here manufactures a device state that cannot be reached by tapping: a hole
 * in the operation log, a full disk, a conflict the server has already recorded. Maestro
 * drives the OS and the UI; it cannot reach inside an encrypted SQLite file, and the
 * cases file 22 asks for are precisely the ones that live in there.
 *
 * **Guarded by `__DEV__` and by a build-time flag.** `runDebugAction` refuses in a
 * production bundle before it looks at the action, so a release build carries a function
 * that returns a refusal and nothing else. A debug hook that could delete an operation
 * from a real officer's log is not a testing convenience, it is a data-loss bug with a
 * URL.
 */

import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';

export const DEBUG_ENABLED = __DEV__;

export type DebugAction =
  | 'save-assessment'
  | 'delete-operation'
  | 'force-conflict'
  | 'set-free-storage'
  | 'set-font-scale'
  | 'reset';

export interface DebugRequest {
  readonly action: string;
  readonly params: Readonly<Record<string, string>>;
}

export interface DebugResult {
  readonly ok: boolean;
  readonly detail: string;
}

/**
 * Overrides the app reads instead of the platform, while a flow is running.
 *
 * Free storage and the text scale both come from the OS, and neither can be set from a
 * test. Rather than skip the two cases that depend on them - a full disk and 200% text,
 * both of which the brief names - the app reads these when they are set, and they can
 * only be set in a development build.
 */
export const overrides: { freeBytes: number | null; fontScale: number | null } = {
  freeBytes: null,
  fontScale: null,
};

export async function runDebugAction(
  request: DebugRequest,
  context: { db: Database; log: OperationLog; saveAssessment: () => Promise<string> },
): Promise<DebugResult> {
  if (!DEBUG_ENABLED) {
    return { ok: false, detail: 'the debug bridge is not present in this build' };
  }

  switch (request.action as DebugAction) {
    case 'save-assessment': {
      const id = await context.saveAssessment();
      return { ok: true, detail: `saved ${id}` };
    }

    case 'delete-operation': {
      // A hole in the log. Produced in the field by a corrupted page or a partial
      // restore, and by nothing a user can do - which is why it needs a hook.
      const seq = Number(request.params.seq ?? '0');
      await context.db.execute('DELETE FROM operation_log WHERE seq = ?', [seq]);
      return { ok: true, detail: `removed seq ${seq}` };
    }

    case 'force-conflict': {
      // The state a restored backup produces: the server's cursor ahead of this device's
      // log, so the next operation lands on a sequence position already consumed.
      await context.db.execute('UPDATE device SET server_cursor = server_cursor + 5 WHERE id = ?', [
        'this',
      ]);
      return { ok: true, detail: 'device cursor advanced past the log' };
    }

    case 'set-free-storage': {
      overrides.freeBytes = Number(request.params.mb ?? '0') * 1024 * 1024;
      return { ok: true, detail: `free storage reported as ${request.params.mb} MB` };
    }

    case 'set-font-scale': {
      overrides.fontScale = Number(request.params.scale ?? '1');
      return { ok: true, detail: `text scale forced to ${request.params.scale}` };
    }

    case 'reset': {
      overrides.freeBytes = null;
      overrides.fontScale = null;
      return { ok: true, detail: 'overrides cleared' };
    }

    default:
      return { ok: false, detail: `unknown debug action ${request.action}` };
  }
}
