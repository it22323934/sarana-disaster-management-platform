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

import { decideNotification } from '../citizen/notification-policy.js';
import type { Database } from '../offline/db/types.js';
import type { OperationLog } from '../offline/log/operation-log.js';

export const DEBUG_ENABLED = __DEV__;

export type DebugAction =
  | 'save-assessment'
  | 'delete-operation'
  | 'force-conflict'
  | 'set-free-storage'
  | 'set-font-scale'
  | 'show-last-report-payload'
  | 'deliver-alert'
  | 'seed-aid'
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

    case 'show-last-report-payload': {
      // Reads the payload that will actually be sent, not the screen that produced it.
      // The people-at-risk case is about the wire, and asserting on a highlighted button
      // would pass while the field was wrong.
      const [row] = await context.db.select<{ payload: string }>(
        "SELECT payload FROM operation_log WHERE entity_type = 'report' ORDER BY seq DESC LIMIT 1",
      );
      return { ok: row !== undefined, detail: row?.payload ?? 'no report has been written' };
    }

    case 'deliver-alert': {
      // Writes an alert into the cache and runs it through the same policy the push
      // handler uses, so the "class 3 always delivers" rule is asserted on the rule and
      // not on a fixture.
      const level = Number(request.params.class ?? '0');
      const now = Date.now();
      await context.db.execute(
        'INSERT OR REPLACE INTO alert_cache (id, headline_si, headline_ta, headline_en, ' +
          'body_si, body_ta, body_en, severity, hazard_type, area_codes, effective_from, ' +
          'effective_to, received_at, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)',
        [
          `debug-alert-${level}`,
          'පරීක්ෂණ අනතුරු ඇඟවීම',
          'சோதனை எச்சரிக்கை',
          'Test warning',
          'ඉවත් වන්න',
          'வெளியேறுங்கள்',
          'Evacuate now',
          level,
          'FLOOD',
          'LK-2-05-020-1015',
          new Date(now - 60_000).toISOString(),
          new Date(now + 6 * 3_600_000).toISOString(),
          new Date(now).toISOString(),
        ],
      );

      const decision = decideNotification({
        kind: 'alert',
        impactClass: level,
        at: new Date(now),
        // Everything muted, which is the point of the test: a class 3 arrives anyway.
        preferences: { minimumAlertClass: 5, aidUpdates: false, reportUpdates: false },
      });
      const detail =
        decision.deliver === 'now'
          ? `delivered now${decision.bypassedMute ? ' (mute bypassed)' : ''}`
          : decision.deliver === 'deferred'
            ? `deferred to ${decision.until.toISOString()}`
            : 'suppressed by preference';
      return { ok: true, detail };
    }

    case 'seed-aid': {
      // A shelter and nothing else. The aid records live on the server and are read
      // through the API; seeding those belongs to the stack, not to a device hook.
      await context.db.execute(
        'INSERT OR REPLACE INTO shelter_cache (id, name_si, name_ta, name_en, ' +
          'gn_division_code, latitude, longitude, capacity, occupancy, status, cached_at) ' +
          'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
          'debug-shelter-1',
          'පල්ලේකැලේ මහා විද්‍යාලය',
          'பள்ளேகலை மகா வித்தியாலயம்',
          'Pallekele Maha Vidyalaya',
          'LK-2-05-020-1015',
          7.2906,
          80.6337,
          200,
          40,
          'OPEN',
          new Date().toISOString(),
        ],
      );
      return { ok: true, detail: 'one shelter cached' };
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
